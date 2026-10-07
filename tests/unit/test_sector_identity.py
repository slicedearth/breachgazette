from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from openpyxl import Workbook

from breachgazette import release
from breachgazette.clients.oaic import (
    EXPECTED_SHEETS,
    ROOT_CAUSES,
    OaicNdbAdapter,
    oaic_metric_id,
)
from breachgazette.clients.xlsx import bounded_workbook
from breachgazette.compare import compare_records
from breachgazette.monitoring import guard_source_record_count
from breachgazette.retention import create_state_backup, state_inventory
from breachgazette.state import PrivateStateStore
from breachgazette.utils import atomic_write_json, sha256_hex


def parse(content, rows=None):
    with bounded_workbook(content, max_rows=5_000, max_columns=64) as workbook:
        return OaicNdbAdapter()._parse(
            workbook,
            {"id": "synthetic", "name": "NDB Data 1 July 2025 to 31 Dec 2025"},
            {"metadata_modified": "2026-01-01"},
            content,
            datetime(2026, 1, 15, tzinfo=UTC),
            identity_rows=rows,
        )


@pytest.fixture
def sector_evidence(tmp_path):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name in EXPECTED_SHEETS:
        workbook.create_sheet(name).append(["Synthetic heading", None])
    causes = sorted(ROOT_CAUSES)
    for month in ["July", "August", "September", "October", "November", "December"]:
        workbook["NDB by month"].append([month, 50])
        for cause in causes:
            workbook["NDB by month"].append([cause, 10])
    for name in ["Time to identify by sector", "Time to notify by sector"]:
        sheet = workbook[name]
        sheet.append(["Synthetic subtitle", None])
        sheet.append(["Interval", "Count"])
        for index in range(5):
            sheet.append([f"Synthetic sector {index}", None])
            for interval in range(4):
                sheet.append([f"Synthetic interval {interval}", 15])
    for index, cause in enumerate(causes):
        workbook["Top 5 sectors by source"].append([f"Synthetic sector {index}", 60])
        workbook["Top 5 sectors by source"].append([cause, 60])
        workbook["Source of breach"].append([cause, 60])
    workbook["Source of breach"]["A1"] = "Synthetic causes, July-December 2025"
    for index in range(10):
        workbook["Individuals affected"].append([f"Synthetic range {index}", 30])
    for index in range(20):
        workbook["Personal information"].append([f"Synthetic information {index}", 20])
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    content = buffer.getvalue()
    rows = {}
    parsed = parse(content, rows)
    assert len(parsed.records) == 121
    indexed = {record.source_record_id: record for record in parsed.records}
    legacy = []
    for (sheet, row), identity in rows.items():
        record = indexed[identity]
        parent = None if sheet == "Top 5 sectors by source" else record.parent_category
        signature = sha256_hex([record.category, parent, record.value.value])[:12]
        legacy.append(
            record.model_copy(
                update={
                    "source_record_id": f"{sheet}:{row}:{signature}",
                    "normalization_version": "1.0",
                    "parent_category": parent,
                }
            )
        )
    root = tmp_path / "synthetic-sector-fixture"
    store = PrivateStateStore(root)
    store.initialize(dataset_class="test_fixture")
    store.write_records("oaic_ndb", legacy)
    store.write_snapshot(parsed.snapshot)
    store.append_events(
        compare_records(
            {},
            {record.source_record_id: record for record in legacy},
            source_id="oaic_ndb",
            current_snapshot=parsed.snapshot.checksum_sha256,
            previous_snapshot=None,
            observed_at=parsed.snapshot.retrieved_at,
            completeness="complete",
        )
    )
    evidence = tmp_path / "synthetic-sector-evidence.xlsx"
    evidence.write_bytes(content)
    # Both complete generations satisfy the existing floor and a 1.0 retained fraction.
    guard_source_record_count("oaic_ndb", previous_count=121, incoming_count=121)
    return root, evidence, legacy


def incomplete_plain_plan(root, legacy, path):
    # Reproduce a previously accepted, collision-free plain plan without using its guard.
    mapping = {}
    for record in legacy:
        mapping[record.source_record_id] = oaic_metric_id(
            sheet=record.source_record_id.rsplit(":", 2)[0],
            period_start=record.reporting_period_start,
            period_end=record.reporting_period_end,
            dimension=record.dimension,
            category=record.category,
            parent=record.parent_category,
            unit=record.unit,
            population_scope=record.population_scope,
        )
    assert len(mapping) == len(set(mapping.values())) == 121
    atomic_write_json(
        path,
        release.IdentityMigrationPlan(
            approved=True,
            state_fingerprint=release._fingerprint(root),
            record_count=121,
            mapping=mapping,
        ),
    )


def test_plain_sector_planning_requires_context_evidence(sector_evidence, tmp_path):
    root, _evidence, _legacy = sector_evidence
    before = state_inventory(root)["checksums"]
    with pytest.raises(ValueError, match="workbook evidence"):
        release.plan_oaic_migration(data_root=root, output=tmp_path / "plain.json")
    assert state_inventory(root)["checksums"] == before


@pytest.mark.parametrize("apply", [False, True])
def test_old_plain_sector_plan_is_rejected_on_validation_and_application(
    sector_evidence,
    tmp_path,
    apply,
):
    root, _evidence, legacy = sector_evidence
    plan = tmp_path / "old-plain.json"
    incomplete_plain_plan(root, legacy, plan)
    backup = tmp_path / "synthetic-backup.zip"
    checksum = create_state_backup(root, backup)["checksum_sha256"]
    before = state_inventory(root)["checksums"]
    with pytest.raises(ValueError, match="workbook evidence"):
        release.migrate_oaic_identities(
            data_root=root,
            plan_path=plan,
            apply=apply,
            backup=backup,
            expected_backup_sha256=checksum,
        )
    assert state_inventory(root)["checksums"] == before


def test_evidence_route_preserves_context_history_and_continuity(sector_evidence, tmp_path):
    root, evidence, legacy = sector_evidence
    store = PrivateStateStore(root)
    events_before = (root / "events/notification-events.json").read_bytes()
    plan_path = tmp_path / "evidence-plan.json"
    release.plan_oaic_migration(data_root=root, output=plan_path, workbook=evidence)
    plan = json.loads(plan_path.read_bytes())
    assert plan["schema_version"] == "1.1"
    assert len(plan["context_updates"]) == 5
    assert len(plan["mapping"]) == len(set(plan["mapping"].values())) == 121
    plan["approved"] = True
    atomic_write_json(plan_path, plan)
    backup = tmp_path / "synthetic-backup.zip"
    checksum = create_state_backup(root, backup)["checksum_sha256"]
    result = release.migrate_oaic_identities(
        data_root=root,
        plan_path=plan_path,
        workbook=evidence,
        backup=backup,
        expected_backup_sha256=checksum,
        apply=True,
    )
    assert result["record_count"] == 121 and result["backup_restore_verified"]
    assert (root / "events/notification-events.json").read_bytes() == events_before
    current = {record.source_record_id: record for record in store.load_records("oaic_ndb")}
    for old in legacy:
        migrated = current[plan["mapping"][old.source_record_id]]
        assert migrated.local_first_observed_time == old.local_first_observed_time
        assert migrated.model_dump(
            exclude={
                "source_record_id",
                "normalization_version",
                "parent_category",
            }
        ) == old.model_dump(
            exclude={
                "source_record_id",
                "normalization_version",
                "parent_category",
            }
        )
    parsed = parse(evidence.read_bytes())
    assert set(current) == {record.source_record_id for record in parsed.records}
    assert not compare_records(
        current,
        {record.source_record_id: record for record in parsed.records},
        source_id="oaic_ndb",
        current_snapshot=parsed.snapshot.checksum_sha256,
        previous_snapshot=store.load_snapshot("oaic_ndb").checksum_sha256,
        observed_at=parsed.snapshot.retrieved_at + timedelta(days=1),
        completeness="complete",
    )


@pytest.mark.parametrize("kind", ["cause", "total"])
def test_plain_sector_context_cannot_retain_an_unreconciled_parent(sector_evidence, tmp_path, kind):
    root, _evidence, records = sector_evidence
    target = next(
        record
        for record in records
        if record.source_record_id.startswith("Top 5 sectors by source:")
        and (record.category in ROOT_CAUSES) == (kind == "cause")
    )
    target.parent_category = "Synthetic unreviewed sector"
    sheet, row, _ = target.source_record_id.rsplit(":", 2)
    signature = sha256_hex([target.category, target.parent_category, target.value.value])[:12]
    target.source_record_id = f"{sheet}:{row}:{signature}"
    PrivateStateStore(root).write_records("oaic_ndb", records)
    before = state_inventory(root)["checksums"]
    with pytest.raises(ValueError, match="workbook evidence"):
        release.plan_oaic_migration(data_root=root, output=tmp_path / "new-plain.json")
    old_plan = tmp_path / "old-plain.json"
    incomplete_plain_plan(root, records, old_plan)
    with pytest.raises(ValueError, match="workbook evidence"):
        release.migrate_oaic_identities(data_root=root, plan_path=old_plan)
    assert state_inventory(root)["checksums"] == before


def test_plain_identity_only_sector_migration_retains_complete_existing_context(
    sector_evidence,
    tmp_path,
):
    root, evidence, records = sector_evidence
    rows = {}
    parsed = parse(evidence.read_bytes(), rows)
    current = {record.source_record_id: record for record in parsed.records}
    for record in records:
        sheet, row, _ = record.source_record_id.rsplit(":", 2)
        record.parent_category = current[rows[(sheet, int(row))]].parent_category
        signature = sha256_hex([record.category, record.parent_category, record.value.value])[:12]
        record.source_record_id = f"{sheet}:{row}:{signature}"
    PrivateStateStore(root).write_records("oaic_ndb", records)
    plan_path = tmp_path / "complete-plain.json"
    release.plan_oaic_migration(data_root=root, output=plan_path)
    plan = json.loads(plan_path.read_bytes())
    assert plan["schema_version"] == "1.0"
    assert set(plan["mapping"].values()) == set(current)
    assert release.migrate_oaic_identities(data_root=root, plan_path=plan_path)["validated"]
