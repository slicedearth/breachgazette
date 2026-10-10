"""Source updates, immutable comparison, fixture isolation, and publication orchestration."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from breachgazette.clients import (
    CaliforniaAdapter,
    CnilAdapter,
    MassachusettsAdapter,
    NetherlandsApAdapter,
    NswAggregateAdapter,
    NswPublicNotificationsAdapter,
    OaicNdbAdapter,
    OaicRegulatoryAdapter,
    UnitedKingdomIcoAdapter,
    WashingtonAdapter,
)
from breachgazette.clients.base import AdapterResult
from breachgazette.compare import compare_records
from breachgazette.contracts import (
    NotificationChange,
    SourceAggregateRecord,
    SourceAnonymizedNotificationRecord,
    SourceNotificationRecord,
    SourceRegulatoryRecord,
    UpdateCheckpoint,
)
from breachgazette.contracts.models import RecordProvenance
from breachgazette.monitoring import guard_source_record_count
from breachgazette.privacy.audit import require_public_safe
from breachgazette.state import PrivateStateStore
from breachgazette.state.recovery import promotion_pending
from breachgazette.state.transaction import (
    copy_candidate,
    discard_candidate,
    promote_candidate,
    state_lock,
)

AdapterFactory = Callable[[], Any]

ADAPTERS: dict[str, AdapterFactory] = {
    "oaic_ndb": OaicNdbAdapter,
    "nsw_public_notifications": NswPublicNotificationsAdapter,
    "nsw_mndb_aggregate": NswAggregateAdapter,
    "oaic_regulatory": OaicRegulatoryAdapter,
    "washington": WashingtonAdapter,
    "california": CaliforniaAdapter,
    "massachusetts": MassachusettsAdapter,
    "france_cnil": CnilAdapter,
    "united_kingdom_ico": UnitedKingdomIcoAdapter,
    "netherlands_ap": NetherlandsApAdapter,
}


def _record_map(records: list[RecordProvenance]) -> dict[str, RecordProvenance]:
    result = {str(record.source_record_id): record for record in records}
    if len(result) != len(records):
        raise ValueError("source snapshot contains duplicate record identifiers")
    return result


def _merge_observation_times(
    previous: dict[str, RecordProvenance],
    current: list[RecordProvenance],
    observed_at: datetime,
) -> list[RecordProvenance]:
    for record in current:
        old = previous.get(str(record.source_record_id))
        if old is not None:
            record.local_first_observed_time = old.local_first_observed_time
        record.local_last_observed_time = observed_at
    return current


def update_source(source_id: str, *, data_root: Path) -> dict[str, Any]:
    if source_id not in ADAPTERS:
        raise ValueError(f"unsupported source: {source_id}")
    root = data_root.resolve()
    with state_lock(root):
        if PrivateStateStore(root).dataset_class() not in {None, "real_source_data"}:
            raise ValueError("refusing to mix fixture and real production state")
        candidate = copy_candidate(root)
        attempted_at = datetime.now(UTC)
        try:
            result = _update_source_generation(source_id, data_root=candidate)
            promote_candidate(root, candidate)
            return result
        except Exception:
            if promotion_pending(root):
                raise
            PrivateStateStore(root).write_checkpoint(
                UpdateCheckpoint(
                    source_id=source_id,
                    attempted_at=attempted_at,
                    completed_at=datetime.now(UTC),
                    status="failed",
                    detail="The source generation was not committed; prior records remain.",
                )
            )
            raise
        finally:
            discard_candidate(root, candidate)


def _update_source_generation(source_id: str, *, data_root: Path) -> dict[str, Any]:
    factory = ADAPTERS.get(source_id)
    if factory is None:
        raise ValueError(f"unsupported source: {source_id}")
    observed_at = datetime.now(UTC)
    store = PrivateStateStore(data_root)
    store.initialize(dataset_class="real_source_data")
    previous_records = store.load_records(source_id)
    previous_by_id = _record_map(previous_records)
    previous_snapshot = store.load_snapshot(source_id)
    store.write_checkpoint(
        UpdateCheckpoint(
            source_id=source_id,
            attempted_at=observed_at,
            status="in_progress",
            detail="Bounded official-source update started.",
        )
    )
    try:
        if (
            source_id == "oaic_ndb"
            and previous_records
            and any(record.normalization_version != "2.0" for record in previous_records)
        ):
            raise ValueError(
                "OAIC identity migration requires review before updating existing state"
            )
        result: AdapterResult = factory().collect(observed_at=observed_at)
        if result.source_id != source_id or result.snapshot.source_id != source_id:
            raise ValueError("adapter source identity does not match the requested source")
        _record_map(result.records)
        if any(record.source_id != source_id for record in result.records):
            raise ValueError("record source identity does not match its snapshot")
        if (
            result.snapshot.records_discovered
            < result.snapshot.records_accepted + result.snapshot.records_rejected
            or result.snapshot.records_accepted > result.snapshot.bounded_limit
        ):
            raise ValueError("snapshot discovery and accepted counts are inconsistent")
        # Grouped anonymised metrics count reports, not retained metric cells.
        if result.snapshot.records_accepted != len(result.records) and source_id not in {
            "france_cnil",
            "united_kingdom_ico",
        }:
            raise ValueError("snapshot accepted count does not match its records")
        guard_source_record_count(
            source_id,
            previous_count=len(previous_records),
            incoming_count=len(result.records),
        )
        result.records = _merge_observation_times(
            previous_by_id,
            result.records,
            observed_at,
        )
        for record in result.records:
            require_public_safe(
                record,
                record_identity=f"{source_id}:{record.source_record_id}",
            )
        current_by_id = _record_map(result.records)
        events = compare_records(
            previous_by_id,
            current_by_id,
            source_id=source_id,
            current_snapshot=result.snapshot.checksum_sha256,
            previous_snapshot=(previous_snapshot.checksum_sha256 if previous_snapshot else None),
            observed_at=observed_at,
            completeness=result.snapshot.completeness,
        )
        changed_ids = {
            event.record_id
            for event in events
            if event.event_type in {"notification_first_observed", "source_record_corrected"}
        }
        for record in result.records:
            old = previous_by_id.get(record.source_record_id)
            record.local_last_material_change_time = (
                observed_at
                if record.source_record_id in changed_ids
                else old.local_last_material_change_time
                if old
                else None
            )
        store.write_records(source_id, result.records)
        store.write_snapshot(result.snapshot)
        events_added = store.append_events(events)
        store.write_checkpoint(
            UpdateCheckpoint(
                source_id=source_id,
                attempted_at=observed_at,
                completed_at=datetime.now(UTC),
                status="complete",
                snapshot_checksum=result.snapshot.checksum_sha256,
                detail=(
                    f"Accepted {len(result.records)} records and appended "
                    f"{events_added} immutable events."
                ),
            )
        )
        return {
            "source_id": source_id,
            "records": len(result.records),
            "rejected": len(result.rejected),
            "events_added": events_added,
            "snapshot": result.snapshot.checksum_sha256,
        }
    except Exception:
        store.write_checkpoint(
            UpdateCheckpoint(
                source_id=source_id,
                attempted_at=observed_at,
                completed_at=datetime.now(UTC),
                status="failed",
                detail="The official-source update failed; previous complete state was preserved.",
            )
        )
        raise


def update_all(*, data_root: Path, sources: list[str] | None = None) -> list[dict[str, Any]]:
    selected = sources or list(ADAPTERS)
    unknown = set(selected) - set(ADAPTERS)
    if unknown:
        raise ValueError(f"unsupported sources: {', '.join(sorted(unknown))}")
    return [update_source(source_id, data_root=data_root) for source_id in selected]


def ingest_fixture(fixture: Path, *, data_root: Path) -> dict[str, Any]:
    if "fixture" not in data_root.name.casefold():
        raise ValueError("fixture data roots must include 'fixture' in the final directory name")
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    if payload.get("dataset_class") != "test_fixture":
        raise ValueError("fixture file must declare dataset_class=test_fixture")
    source_id = str(payload["source_id"])
    model_by_type: dict[str, type[RecordProvenance]] = {
        "aggregate": SourceAggregateRecord,
        "anonymized_notification": SourceAnonymizedNotificationRecord,
        "notification": SourceNotificationRecord,
        "regulatory": SourceRegulatoryRecord,
    }
    records: list[RecordProvenance] = []
    for item in payload.get("records", []):
        model = model_by_type.get(str(item.get("record_type")))
        if model is None:
            raise ValueError("fixture record type is unsupported")
        records.append(model.model_validate(item))
    store = PrivateStateStore(data_root)
    store.initialize(dataset_class="test_fixture")
    store.write_records(source_id, records)
    return {"source_id": source_id, "records": len(records), "dataset_class": "test_fixture"}


def compare_summary(*, data_root: Path) -> dict[str, Any]:
    store = PrivateStateStore(data_root)
    events: list[NotificationChange] = store.load_events()
    counts: dict[str, int] = {}
    for event in events:
        counts[event.event_type] = counts.get(event.event_type, 0) + 1
    return {"events": len(events), "event_types": dict(sorted(counts.items()))}
