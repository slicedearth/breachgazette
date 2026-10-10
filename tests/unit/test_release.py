from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from breachgazette import release
from breachgazette.cli import app
from breachgazette.clients.oaic import EXPECTED_SHEETS, plan_identity_migration
from breachgazette.compare import compare_records
from breachgazette.contracts import SourceAggregateRecord, SourceSnapshot
from breachgazette.retention import create_state_backup, state_inventory
from breachgazette.state import PrivateStateStore
from breachgazette.state.transaction import state_lock
from breachgazette.utils import atomic_write_json, sha256_hex


@pytest.fixture
def legacy_root(tmp_path: Path) -> Path:
    root = tmp_path / "synthetic-fixture-state"
    store = PrivateStateStore(root)
    store.initialize(dataset_class="test_fixture")
    observed = datetime(2026, 1, 15, tzinfo=UTC)
    records = [
        SourceAggregateRecord(
            source_id="oaic_ndb",
            source_record_id=f"{EXPECTED_SHEETS[1]}:{index}:synthetic",
            source_url="https://example.gov/synthetic",
            source_revision="synthetic revision",
            source_checksum="a" * 64,
            source_completeness="complete",
            source_retrieval_time=observed,
            local_first_observed_time=observed,
            local_last_observed_time=observed,
            local_last_material_change_time=observed,
            parser_version="1.0",
            normalization_version="1.0",
            limitations=["Synthetic test metric."],
            regulator="Example regulator",
            reporting_scheme="Synthetic reporting scheme",
            publication_level="national_aggregate",
            reporting_period_start=date(2025, 7, 1),
            reporting_period_end=date(2025, 12, 31),
            dimension="month",
            category=category,
            value={"value": 101 + index, "origin": "source_observed"},
            unit="notifications",
            population_scope="Synthetic reporting population",
        )
        for index, category in enumerate(("July", "August"))
    ]
    store.write_records("oaic_ndb", list(records))
    store.write_snapshot(
        SourceSnapshot(
            source_id="oaic_ndb",
            retrieved_at=observed,
            completed_at=observed,
            revision="synthetic",
            checksum_sha256="a" * 64,
            completeness="complete",
            records_discovered=2,
            records_accepted=2,
            records_rejected=0,
            bounded_limit=2_000,
            latest_attempted_update=observed,
        )
    )
    store.append_events(
        compare_records(
            {},
            {record.source_record_id: record for record in records},
            source_id="oaic_ndb",
            current_snapshot="a" * 64,
            previous_snapshot=None,
            observed_at=observed,
            completeness="complete",
        )
    )
    (root / ".git").mkdir()
    (root / ".git" / "marker").write_text("synthetic repository metadata")
    return root


def _plan(root: Path, tmp_path: Path, *, approved: bool = False) -> Path:
    path = tmp_path / "private-plan.json"
    release.plan_oaic_migration(data_root=root, output=path)
    if approved:
        payload = json.loads(path.read_text())
        payload["approved"] = True
        atomic_write_json(path, payload)
    return path


def _tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256_hex(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


def test_plan_and_default_validation_never_mutate_state(legacy_root, tmp_path) -> None:
    before = _tree(legacy_root)
    plan = _plan(legacy_root, tmp_path)
    assert plan.stat().st_mode & 0o777 == 0o600
    assert not json.loads(plan.read_text())["approved"]
    result = release.migrate_oaic_identities(data_root=legacy_root, plan_path=plan)
    assert result == {
        "validated": True,
        "applied": False,
        "approved": False,
        "record_count": 2,
        "backup_restore_verified": False,
    }
    assert _tree(legacy_root) == before
    assert not (legacy_root.parent / f".{legacy_root.name}.lock").exists()
    with pytest.raises(FileExistsError):
        release.plan_oaic_migration(data_root=legacy_root, output=plan)
    with pytest.raises(ValueError, match="outside authoritative"):
        release.plan_oaic_migration(data_root=legacy_root, output=legacy_root / "reviews/plan.json")


def test_reviewed_migration_verifies_restore_and_preserves_history(legacy_root, tmp_path) -> None:
    before_tree = _tree(legacy_root)
    original = PrivateStateStore(legacy_root)
    records = original.load_records("oaic_ndb")
    history = original.load_events()
    snapshot = original.load_snapshot("oaic_ndb")
    marker = (legacy_root / "metadata/dataset-class.json").read_bytes()
    plan = _plan(legacy_root, tmp_path, approved=True)
    backup = tmp_path / "backup.zip"
    backup_info = create_state_backup(legacy_root, backup)
    result = release.migrate_oaic_identities(
        data_root=legacy_root,
        plan_path=plan,
        backup=backup,
        expected_backup_sha256=backup_info["checksum_sha256"],
        apply=True,
    )
    assert result["applied"] and result["backup_restore_verified"]
    mapping = json.loads(plan.read_text())["mapping"]
    after = original.load_records("oaic_ndb")
    for before, current in zip(records, after, strict=True):
        assert (
            current.model_dump()
            == before.model_copy(
                update={
                    "source_record_id": mapping[before.source_record_id],
                    "normalization_version": "2.0",
                }
            ).model_dump()
        )
    assert original.load_events() == history
    assert original.load_snapshot("oaic_ndb") == snapshot
    assert (legacy_root / "metadata/dataset-class.json").read_bytes() == marker
    assert original.dataset_class() == "test_fixture"
    assert (legacy_root / ".git/marker").read_text() == "synthetic repository metadata"
    bridge = json.loads((legacy_root / "reviews/oaic-identity-bridge.json").read_text())
    assert bridge["mapping"] == mapping
    after_tree = _tree(legacy_root)
    for path, checksum in before_tree.items():
        if path != "state/oaic_ndb.json":
            assert after_tree[path] == checksum
    before_replay = _tree(legacy_root)
    with pytest.raises(ValueError, match="generation"):
        release.migrate_oaic_identities(
            data_root=legacy_root,
            plan_path=plan,
            backup=backup,
            expected_backup_sha256=backup_info["checksum_sha256"],
            apply=True,
        )
    assert _tree(legacy_root) == before_replay
    assert not list(tmp_path.glob(".*-candidate-*"))


@pytest.mark.parametrize("defect", ["approval", "backup", "checksum", "stale", "mapping"])
def test_apply_rejects_unreviewed_or_mismatched_inputs(legacy_root, tmp_path, defect) -> None:
    plan = _plan(legacy_root, tmp_path, approved=defect != "approval")
    backup = tmp_path / "backup.zip"
    checksum = create_state_backup(legacy_root, backup)["checksum_sha256"]
    if defect == "checksum":
        checksum = "0" * 64
    if defect == "stale":
        atomic_write_json(legacy_root / "reports/new-observation.json", {"synthetic": True})
    if defect == "mapping":
        payload = json.loads(plan.read_text())
        payload["mapping"][next(iter(payload["mapping"]))] = "oaic:v2:" + "f" * 32
        atomic_write_json(plan, payload)
    before = _tree(legacy_root)
    with pytest.raises(ValueError):
        release.migrate_oaic_identities(
            data_root=legacy_root,
            plan_path=plan,
            backup=None if defect == "backup" else backup,
            expected_backup_sha256=checksum,
            apply=True,
        )
    assert _tree(legacy_root) == before


def test_backup_must_restore_the_exact_reviewed_generation(legacy_root, tmp_path) -> None:
    backup = tmp_path / "older-backup.zip"
    checksum = create_state_backup(legacy_root, backup)["checksum_sha256"]
    atomic_write_json(legacy_root / "reports/observation.json", {"synthetic": True})
    plan = _plan(legacy_root, tmp_path, approved=True)
    before = _tree(legacy_root)
    with pytest.raises(ValueError, match="reviewed state generation"):
        release.migrate_oaic_identities(
            data_root=legacy_root,
            plan_path=plan,
            backup=backup,
            expected_backup_sha256=checksum,
            apply=True,
        )
    assert _tree(legacy_root) == before


@pytest.mark.parametrize("boundary", ["write", "bridge", "promotion"])
def test_migration_failure_keeps_the_prior_generation(legacy_root, tmp_path, monkeypatch, boundary):
    plan = _plan(legacy_root, tmp_path, approved=True)
    backup = tmp_path / "backup.zip"
    checksum = create_state_backup(legacy_root, backup)["checksum_sha256"]
    before = _tree(legacy_root)

    def fail(*args, **kwargs):
        raise OSError("Synthetic failure; never source data.")

    if boundary == "write":
        monkeypatch.setattr(PrivateStateStore, "write_records", fail)
    else:
        monkeypatch.setattr(
            release, "atomic_write_json" if boundary == "bridge" else "promote_candidate", fail
        )
    with pytest.raises(OSError):
        release.migrate_oaic_identities(
            data_root=legacy_root,
            plan_path=plan,
            backup=backup,
            expected_backup_sha256=checksum,
            apply=True,
        )
    assert _tree(legacy_root) == before
    assert not list(tmp_path.glob(".*-candidate-*"))


def test_migration_respects_the_single_writer_lock(legacy_root, tmp_path) -> None:
    plan = _plan(legacy_root, tmp_path, approved=True)
    with state_lock(legacy_root), pytest.raises(RuntimeError, match="another writer"):
        release.migrate_oaic_identities(
            data_root=legacy_root,
            plan_path=plan,
            backup=tmp_path / "unused.zip",
            expected_backup_sha256="0" * 64,
            apply=True,
        )


def test_plan_rejects_duplicate_json_keys_and_symbolic_links(legacy_root, tmp_path) -> None:
    plan = _plan(legacy_root, tmp_path)
    duplicate = plan.read_text().replace('"approved":false', '"approved":false,"approved":true')
    plan.write_text(duplicate)
    with pytest.raises(ValueError, match="duplicate keys"):
        release.migrate_oaic_identities(data_root=legacy_root, plan_path=plan)
    link = tmp_path / "plan-link.json"
    link.symlink_to(plan)
    with pytest.raises(ValueError, match="symbolic"):
        release.migrate_oaic_identities(data_root=legacy_root, plan_path=link)


def test_fixture_preflight_is_read_only_and_not_a_release_pass(legacy_root) -> None:
    before = _tree(legacy_root)
    report = release.deployment_preflight(data_root=legacy_root)
    assert not report["passed"]
    assert not report["checks"]["real_dataset_class"]
    assert not report["checks"]["oaic_identities_current"]
    assert not report["checks"]["source_health_valid"]
    assert not report["checks"]["publication_quality_and_privacy_valid"]
    assert _tree(legacy_root) == before
    assert not (legacy_root.parent / f".{legacy_root.name}.lock").exists()


def _current_metrics(root: Path) -> None:
    store = PrivateStateStore(root)
    records = [
        SourceAggregateRecord.model_validate(item.model_dump())
        for item in store.load_records("oaic_ndb")
    ]
    mapping = plan_identity_migration(records)
    store.write_records(
        "oaic_ndb",
        [
            item.model_copy(
                update={
                    "source_record_id": mapping[item.source_record_id],
                    "normalization_version": "2.0",
                }
            )
            for item in records
        ],
    )


def test_preflight_orchestration_detects_publication_failure_and_state_drift(
    legacy_root,
    monkeypatch,
) -> None:
    _current_metrics(legacy_root)
    # Inject production-status controls, never relabel the fixture or retrieve live state.
    monkeypatch.setattr(PrivateStateStore, "dataset_class", lambda _: "real_source_data")
    monkeypatch.setattr(
        release, "build_source_health_report", lambda **_: SimpleNamespace(passed=True)
    )
    monkeypatch.setattr(release, "build_site_data", lambda **_: {"quality_passed": True})
    monkeypatch.setattr(release, "audit_public_tree", lambda _: {"passed": True})
    before = _tree(legacy_root)
    assert release.deployment_preflight(data_root=legacy_root)["passed"]
    assert _tree(legacy_root) == before

    def rejected(**_):
        raise RuntimeError("synthetic private contact alice@example.test")

    monkeypatch.setattr(release, "build_site_data", rejected)
    report = release.deployment_preflight(data_root=legacy_root)
    assert not report["passed"]
    assert "alice" not in json.dumps(report)

    def changed(**_):
        atomic_write_json(legacy_root / "reports/concurrent.json", {"synthetic": True})
        return {"quality_passed": True}

    monkeypatch.setattr(release, "build_site_data", changed)
    assert not release.deployment_preflight(data_root=legacy_root)["checks"][
        "state_generation_unchanged"
    ]


def test_preflight_does_not_apply_migration_or_bypass_a_stale_health_gate(legacy_root, monkeypatch):
    _current_metrics(legacy_root)
    monkeypatch.setattr(PrivateStateStore, "dataset_class", lambda _: "real_source_data")
    monkeypatch.setattr(
        release, "build_source_health_report", lambda **_: SimpleNamespace(passed=False)
    )

    def unexpected(**_):
        pytest.fail("a failed preflight must not attempt publication")

    monkeypatch.setattr(release, "build_site_data", unexpected)
    assert not release.deployment_preflight(data_root=legacy_root)["passed"]


@pytest.mark.parametrize("outside_workflow", [None, "false", "True", "1"])
def test_exact_workflow_checkout_exception_is_read_only(tmp_path, monkeypatch, outside_workflow):
    checkout = tmp_path / "synthetic-checkout"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text("# synthetic marker")
    root = checkout / ".private-production-data"
    root.mkdir()
    monkeypatch.setattr(release, "_source_checkout", lambda: checkout)
    if outside_workflow is None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    else:
        monkeypatch.setenv("GITHUB_ACTIONS", outside_workflow)
    assert not release.deployment_preflight(data_root=root)["checks"]["private_root_valid"]
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert release.deployment_preflight(data_root=root)["checks"]["private_root_valid"]
    with pytest.raises(ValueError, match="source checkout"):
        release.plan_oaic_migration(data_root=root, output=tmp_path / "plan.json")
    other = checkout / "other-state"
    other.mkdir()
    assert not release.deployment_preflight(data_root=other)["checks"]["private_root_valid"]


def test_release_cli_is_sanitised_and_dry_run_by_default(legacy_root, tmp_path) -> None:
    runner = CliRunner()
    plan = tmp_path / "cli-plan.json"
    before = _tree(legacy_root)
    planned = runner.invoke(
        app,
        ["plan-oaic-migration", "--data-root", str(legacy_root), "--output", str(plan), "--json"],
    )
    assert planned.exit_code == 0
    assert json.loads(planned.stdout) == {"planned": True, "approved": False, "record_count": 2}
    preview = runner.invoke(
        app,
        ["migrate-oaic-identities", "--data-root", str(legacy_root), "--plan", str(plan), "--json"],
    )
    assert preview.exit_code == 0
    assert not json.loads(preview.stdout)["applied"]
    refused = runner.invoke(
        app,
        [
            "migrate-oaic-identities",
            "--data-root",
            str(legacy_root),
            "--plan",
            str(plan),
            "--apply",
            "--json",
        ],
    )
    assert refused.exit_code == 2
    assert json.loads(refused.stdout) == {"passed": False, "error": "identity_transition_failed"}
    preflight = runner.invoke(
        app, ["deployment-preflight", "--data-root", str(legacy_root), "--json"]
    )
    assert preflight.exit_code == 2
    assert not json.loads(preflight.stdout)["passed"]
    assert "Traceback" not in preflight.output
    assert _tree(legacy_root) == before
    missing = release.deployment_preflight(data_root=tmp_path / "missing")
    assert not missing["passed"]


def test_migration_plan_changes_are_bound_to_all_managed_state(legacy_root, tmp_path):
    plan = _plan(legacy_root, tmp_path)
    before = state_inventory(legacy_root)["checksums"]
    atomic_write_json(legacy_root / "reviews/private-review.json", {"synthetic": True})
    assert state_inventory(legacy_root)["checksums"] != before
    with pytest.raises(ValueError, match="generation"):
        release.migrate_oaic_identities(data_root=legacy_root, plan_path=plan)


def test_installed_wheel_recognises_checkout_targets(tmp_path, monkeypatch):
    checkout = tmp_path / "synthetic-public-checkout"
    (checkout / "src/breachgazette").mkdir(parents=True)
    (checkout / "site").mkdir()
    (checkout / "pyproject.toml").write_text("# synthetic project")
    (checkout / "site/package.json").write_text("{}")
    state = checkout / "private-state"
    state.mkdir()
    monkeypatch.setattr(release, "_source_checkout", lambda: tmp_path / "installed-library")
    assert not release.deployment_preflight(data_root=state)["checks"]["private_root_valid"]
    with pytest.raises(ValueError, match="source checkout"):
        release.plan_oaic_migration(data_root=state, output=tmp_path / "plan.json")
    with pytest.raises(ValueError, match="source checkout"):
        release._outside_state(checkout / "private-plan.json", tmp_path / "other-state")
