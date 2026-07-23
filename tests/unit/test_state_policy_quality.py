from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from breachgazette.clients.base import source_snapshot
from breachgazette.contracts import (
    MonitoringCatalogue,
    NotificationChange,
    SourceMonitoringPolicy,
    SourceNotificationRecord,
    UpdateCheckpoint,
)
from breachgazette.contracts.enums import Completeness
from breachgazette.monitoring import (
    SourceDriftError,
    build_source_health_report,
    guard_source_record_count,
    load_monitoring_catalogue,
)
from breachgazette.policies import load_source_policies
from breachgazette.publish.builder import (
    SEARCH_PARTITION_SIZE,
    _build_search_assets,
    _fnv1a,
    _search_trigrams,
    audit_public_tree,
    build_site_data,
)
from breachgazette.quality import DataQualityError, build_quality_report
from breachgazette.quality.temporal import exclude_temporal_conflicts
from breachgazette.state import PrivateStateStore


def test_source_policy_catalogue_is_complete() -> None:
    policies = load_source_policies()
    assert set(policies) == {
        "oaic_ndb",
        "nsw_public_notifications",
        "nsw_mndb_aggregate",
        "oaic_regulatory",
        "washington",
        "california",
        "massachusetts",
        "hhs",
    }
    assert policies["hhs"].implemented is False
    assert all(str(policy.source_url).startswith("https://") for policy in policies.values())
    monitoring = load_monitoring_catalogue()
    assert set(monitoring.sources) == set(policies) - {"hhs"}


def test_source_policy_catalogue_rejects_stale_or_future_rights_reviews(
    tmp_path: Path,
) -> None:
    source = Path(__file__).resolve().parents[2] / "sources" / "policies"
    stale_root = tmp_path / "stale"
    shutil.copytree(source, stale_root / "sources" / "policies")
    stale_path = stale_root / "sources" / "policies" / "washington.json"
    stale_payload = json.loads(stale_path.read_text(encoding="utf-8"))
    stale_payload["rights_reviewed_on"] = "2000-01-01"
    stale_path.write_text(json.dumps(stale_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="rights review is stale: washington"):
        load_source_policies(stale_root)

    future_root = tmp_path / "future"
    shutil.copytree(source, future_root / "sources" / "policies")
    future_path = future_root / "sources" / "policies" / "washington.json"
    future_payload = json.loads(future_path.read_text(encoding="utf-8"))
    future_payload["rights_reviewed_on"] = "2999-01-01"
    future_path.write_text(json.dumps(future_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="rights review is future-dated: washington"):
        load_source_policies(future_root)


def test_private_state_is_atomic_and_refuses_fixture_mixing(
    tmp_path: Path, notification_factory
) -> None:
    store = PrivateStateStore(tmp_path / "private")
    store.initialize(dataset_class="real_source_data")
    assert store.dataset_class() == "real_source_data"
    with pytest.raises(ValueError, match="mix"):
        store.initialize(dataset_class="test_fixture")
    record = SourceNotificationRecord.model_validate(
        notification_factory().model_dump(exclude={"canonical_organization_id"})
    )
    store.write_records("washington", [record])
    assert store.load_records("washington")[0].source_record_id == "record-1"
    assert store.source_ids() == ["washington"]
    assert store.inventory()["sources"] == {"washington": 1}


def test_snapshot_checkpoint_and_event_round_trip(tmp_path: Path) -> None:
    store = PrivateStateStore(tmp_path)
    observed = datetime(2026, 1, 1, tzinfo=UTC)
    snapshot = source_snapshot(
        source_id="washington",
        retrieved_at=observed,
        revision="revision",
        checksum="a" * 64,
        completeness="complete",
        discovered=1,
        accepted=1,
        rejected=0,
        bounded_limit=10,
    )
    store.write_snapshot(snapshot)
    assert store.load_snapshot("washington") == snapshot
    store.write_checkpoint(
        UpdateCheckpoint(
            source_id="washington",
            attempted_at=observed,
            completed_at=observed,
            status="complete",
            snapshot_checksum="a" * 64,
            detail="Complete.",
        )
    )
    event = NotificationChange(
        event_id="b" * 64,
        source_id="washington",
        record_id="record-1",
        event_type="notification_first_observed",
        after_value={"record": "record-1"},
        current_snapshot="a" * 64,
        source_completeness=Completeness.COMPLETE,
        detector_version="1.0",
        first_observed_time=observed,
        reason="Observed.",
    )
    assert store.append_events([event]) == 1
    assert store.append_events([event]) == 0
    assert store.load_events() == [event]
    assert store.load_checkpoint("washington") is not None


def test_source_count_guards_block_suspicious_replacement() -> None:
    policy = SourceMonitoringPolicy(
        source_id="washington",
        stale_after_hours=240,
        minimum_records=10,
        minimum_retained_fraction=0.9,
        maximum_growth_factor=1.5,
    )
    guard_source_record_count(
        "washington",
        previous_count=100,
        incoming_count=95,
        policy=policy,
    )
    with pytest.raises(SourceDriftError, match="below its reviewed floor"):
        guard_source_record_count(
            "washington",
            previous_count=0,
            incoming_count=9,
            policy=policy,
        )
    with pytest.raises(SourceDriftError, match="retained too few"):
        guard_source_record_count(
            "washington",
            previous_count=100,
            incoming_count=50,
            policy=policy,
        )
    with pytest.raises(SourceDriftError, match="grew beyond"):
        guard_source_record_count(
            "washington",
            previous_count=100,
            incoming_count=151,
            policy=policy,
        )


def test_source_health_reports_latest_failed_checkpoint(
    tmp_path: Path,
    notification_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "health-state"
    store = PrivateStateStore(root)
    store.initialize(dataset_class="real_source_data")
    observed = datetime.now(UTC)
    record = SourceNotificationRecord.model_validate(
        notification_factory().model_dump(exclude={"canonical_organization_id"})
    )
    store.write_records("washington", [record])
    store.write_snapshot(
        source_snapshot(
            source_id="washington",
            retrieved_at=observed,
            revision="revision",
            checksum="a" * 64,
            completeness="complete",
            discovered=1,
            accepted=1,
            rejected=0,
            bounded_limit=10,
        )
    )
    monitoring = MonitoringCatalogue(
        schedule_utc="23 17 * * 1",
        sources={
            "washington": SourceMonitoringPolicy(
                source_id="washington",
                stale_after_hours=240,
                minimum_records=1,
                minimum_retained_fraction=0.5,
                maximum_growth_factor=2,
            )
        },
    )
    monkeypatch.setattr(
        "breachgazette.monitoring.load_monitoring_catalogue",
        lambda: monitoring,
    )
    assert build_source_health_report(data_root=root, generated_at=observed).passed is True
    store.write_checkpoint(
        UpdateCheckpoint(
            source_id="washington",
            attempted_at=observed,
            completed_at=observed,
            status="failed",
            detail="Previous complete state was preserved.",
        )
    )
    report = build_source_health_report(data_root=root, generated_at=observed)
    assert report.passed is False
    assert report.sources[0].status == "failed_update"


def test_invalid_state_and_dataset_class_fail_closed(tmp_path: Path) -> None:
    store = PrivateStateStore(tmp_path)
    with pytest.raises(ValueError, match="unsupported dataset"):
        store.initialize(dataset_class="unknown")
    state = store.state_path("bad")
    state.parent.mkdir(parents=True)
    state.write_text('{"not":"a list"}', encoding="utf-8")
    with pytest.raises(ValueError, match="not a list"):
        store.load_records("bad")


def test_quality_report_rejects_fixture_or_missing_required_sources(
    notification_factory,
) -> None:
    with pytest.raises(DataQualityError, match="fixture_isolation"):
        build_quality_report(
            dataset_class="test_fixture",
            records_by_source={"washington": [notification_factory()]},
            snapshots=[],
        )
    with pytest.raises(DataQualityError, match="required_sources"):
        build_quality_report(
            dataset_class="real_source_data",
            records_by_source={"washington": [notification_factory()]},
            snapshots=[],
        )


def test_production_builder_refuses_fixture_root(tmp_path: Path) -> None:
    root = tmp_path / "fixture-root"
    PrivateStateStore(root).initialize(dataset_class="test_fixture")
    with pytest.raises(DataQualityError, match="real source"):
        build_site_data(data_root=root, output=tmp_path / "output")


def test_existing_california_state_excludes_temporal_conflicts_from_publication(
    notification_factory,
) -> None:
    record = notification_factory(
        source_id="california",
        dates=[
            {
                "meaning": "occurrence_start",
                "raw_value": "11/20/2027",
                "normalized_date": "2027-11-20",
                "origin": "source_observed",
                "state": "present",
            },
            {
                "meaning": "regulator_submission_date",
                "raw_value": "07/03/2024",
                "normalized_date": "2024-07-03",
                "origin": "source_observed",
                "state": "present",
            },
        ],
    )

    assert exclude_temporal_conflicts(record) == 1
    assert record.dates[0].raw_value == "11/20/2027"
    assert record.dates[0].normalized_date is None
    assert record.dates[0].state == "source_conflict"
    assert exclude_temporal_conflicts(record) == 0
    assert len(
        [
            item
            for item in record.limitations
            if "post-dates the regulator submission date" in item
        ]
    ) == 1


def test_search_assets_are_partitioned_and_bounded(notification_factory) -> None:
    records = [
        notification_factory(record_id=f"record-{index}")
        for index in range(SEARCH_PARTITION_SIZE + 1)
    ]
    manifest, partitions = _build_search_assets(
        records,
        detail_ids=set(),
        generated_at=datetime.now(UTC),
    )
    assert manifest["record_count"] == SEARCH_PARTITION_SIZE + 1
    assert len(partitions) == 2
    assert sum(partition["count"] for partition in manifest["partitions"]) == len(records)
    assert all(len(payload["records"]) <= SEARCH_PARTITION_SIZE for _, payload in partitions)
    assert manifest["query_routing"] == {
        "algorithm": "normalized_trigram_bloom",
        "encoding": "hex",
        "bits": 16_384,
        "hashes": 3,
        "minimum_query_length": 3,
    }
    bloom = bytes.fromhex(manifest["partitions"][0]["query_bloom"])
    for gram in _search_trigrams("example health"):
        assert all(
            bloom[
                (_fnv1a(f"{seed}|{gram}") % manifest["query_routing"]["bits"]) // 8
            ]
            & (
                1
                << (
                    _fnv1a(f"{seed}|{gram}")
                    % manifest["query_routing"]["bits"]
                    % 8
                )
            )
            for seed in range(manifest["query_routing"]["hashes"])
        )


def test_production_builder_emits_minimised_real_publication(
    tmp_path: Path, notification_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "real-state"
    store = PrivateStateStore(root)
    store.initialize(dataset_class="real_source_data")
    source_ids = (
        "oaic_ndb",
        "nsw_public_notifications",
        "nsw_mndb_aggregate",
        "oaic_regulatory",
        "washington",
        "california",
        "massachusetts",
    )
    observed = datetime.now(UTC)
    monitoring = MonitoringCatalogue(
        schedule_utc="23 17 * * 1",
        sources={
            source_id: SourceMonitoringPolicy(
                source_id=source_id,
                stale_after_hours=240,
                minimum_records=1,
                minimum_retained_fraction=0.5,
                maximum_growth_factor=2,
            )
            for source_id in source_ids
        },
    )
    monkeypatch.setattr(
        "breachgazette.monitoring.load_monitoring_catalogue",
        lambda: monitoring,
    )
    reviews = root / "reviews"
    reviews.mkdir(parents=True)
    (reviews / "organization-aliases.yml").write_text(
        'schema_version: "2.0"\ndecisions: []\n',
        encoding="utf-8",
    )
    (reviews / "relationship-decisions.yml").write_text(
        'schema_version: "1.0"\ndecisions: []\n',
        encoding="utf-8",
    )
    for index, source_id in enumerate(source_ids):
        normalized = notification_factory(
            source_id=source_id,
            record_id=f"{source_id}-record",
            name=f"Example Organization {chr(65 + index)}",
        )
        record = normalized.model_dump(exclude={"canonical_organization_id"})
        record["source_id"] = source_id
        store.write_records(
            source_id,
            [SourceNotificationRecord.model_validate(record)],
        )
        store.write_snapshot(
            source_snapshot(
                source_id=source_id,
                retrieved_at=observed,
                revision=f"revision-{source_id}",
                checksum=(f"{index + 1:x}" * 64)[:64],
                completeness="complete",
                discovered=1,
                accepted=1,
                rejected=0,
                bounded_limit=10,
            )
        )
    output = tmp_path / "publication"
    result = build_site_data(data_root=root, output=output)
    assert result["quality_passed"] is True
    assert result["records"]["notifications"] == len(source_ids)
    assert (output / "publication.json").is_file()
    publication = json.loads((output / "publication.json").read_text(encoding="utf-8"))
    assert "latest_notifications" not in publication
    assert not (output / "notifications.json").exists()
    assert (output / "search-manifest.json").is_file()
    search_manifest = json.loads(
        (output / "search-manifest.json").read_text(encoding="utf-8")
    )
    assert search_manifest["record_count"] == len(source_ids)
    assert len(list((output / "search-partitions").glob("*.json"))) == len(source_ids)
    assert (output / "source-health.json").is_file()
    assert audit_public_tree(output)["passed"] is True


def test_public_tree_audit_passes_safe_tree_and_rejects_remote_assets(tmp_path: Path) -> None:
    safe = tmp_path / "safe"
    safe.mkdir()
    (safe / "index.html").write_text("<p>Safe static page</p>", encoding="utf-8")
    (safe / "_headers").write_text("/*\n  X-Frame-Options: DENY\n", encoding="utf-8")
    report = audit_public_tree(safe)
    assert report["passed"] is True
    assert report["files"] == 2
    assert report["html_files"] == 1
    with pytest.raises(DataQualityError, match="budget"):
        audit_public_tree(safe, max_files=0)
    with pytest.raises(DataQualityError, match="HTML page exceeds"):
        audit_public_tree(safe, max_html_bytes=5)
    (safe / "bad.js").write_text('google-analytics("x")', encoding="utf-8")
    with pytest.raises(DataQualityError, match="forbidden marker"):
        audit_public_tree(safe)
    with pytest.raises(ValueError, match="does not exist"):
        audit_public_tree(tmp_path / "missing")


@pytest.mark.parametrize(
    "filename",
    [
        ".env",
        "archive.zip",
        "bundle.js.map",
        "private.pem",
        "state.sqlite",
    ],
)
def test_public_tree_audit_rejects_sensitive_or_unknown_file_types(
    tmp_path: Path,
    filename: str,
) -> None:
    public = tmp_path / "public"
    public.mkdir()
    (public / "index.html").write_text("<p>Safe static page</p>", encoding="utf-8")
    (public / filename).write_text("not public", encoding="utf-8")
    with pytest.raises(DataQualityError, match="not allowed"):
        audit_public_tree(public)


def test_public_tree_audit_rejects_symbolic_links(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    target = tmp_path / "private.txt"
    target.write_text("private state", encoding="utf-8")
    (public / "linked.txt").symlink_to(target)
    with pytest.raises(DataQualityError, match="symbolic links"):
        audit_public_tree(public)
