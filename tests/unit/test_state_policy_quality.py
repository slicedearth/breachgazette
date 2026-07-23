from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from breachgazette.clients.base import source_snapshot
from breachgazette.contracts import NotificationChange, SourceNotificationRecord, UpdateCheckpoint
from breachgazette.contracts.enums import Completeness
from breachgazette.policies import load_source_policies
from breachgazette.publish.builder import audit_public_tree, build_site_data
from breachgazette.quality import DataQualityError, build_quality_report
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
        "hhs",
    }
    assert policies["hhs"].implemented is False
    assert all(str(policy.source_url).startswith("https://") for policy in policies.values())


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


def test_production_builder_emits_minimised_real_publication(
    tmp_path: Path, notification_factory
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
    )
    observed = datetime(2026, 1, 1, tzinfo=UTC)
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
    assert (output / "notifications.json").is_file()
    assert audit_public_tree(output)["passed"] is True


def test_public_tree_audit_passes_safe_tree_and_rejects_remote_assets(tmp_path: Path) -> None:
    safe = tmp_path / "safe"
    safe.mkdir()
    (safe / "index.html").write_text("<p>Safe static page</p>", encoding="utf-8")
    assert audit_public_tree(safe)["passed"] is True
    (safe / "bad.js").write_text('google-analytics("x")', encoding="utf-8")
    with pytest.raises(DataQualityError, match="forbidden marker"):
        audit_public_tree(safe)
    with pytest.raises(ValueError, match="does not exist"):
        audit_public_tree(tmp_path / "missing")
