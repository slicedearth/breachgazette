"""Filesystem-backed private state with explicit dataset-class markers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from breachgazette.contracts import (
    NotificationChange,
    SourceAggregateRecord,
    SourceNotificationRecord,
    SourceRegulatoryRecord,
    SourceSnapshot,
    UpdateCheckpoint,
)
from breachgazette.contracts.models import RecordProvenance
from breachgazette.utils import atomic_write_json, read_json

RECORD_MODELS: dict[str, type[RecordProvenance]] = {
    "aggregate": SourceAggregateRecord,
    "notification": SourceNotificationRecord,
    "regulatory": SourceRegulatoryRecord,
}


class PrivateStateStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def initialize(self, *, dataset_class: str) -> None:
        if dataset_class not in {"real_source_data", "test_fixture"}:
            raise ValueError("unsupported dataset class")
        marker = self.root / "metadata" / "dataset-class.json"
        existing = read_json(marker)
        if existing and existing.get("dataset_class") != dataset_class:
            raise ValueError("refusing to mix fixture and real production state")
        atomic_write_json(
            marker,
            {
                "schema_version": "1.0",
                "dataset_class": dataset_class,
                "updated_at": datetime.now(UTC),
            },
        )

    def dataset_class(self) -> str | None:
        marker = read_json(self.root / "metadata" / "dataset-class.json", {})
        return marker.get("dataset_class") if isinstance(marker, dict) else None

    def state_path(self, source_id: str) -> Path:
        return self.root / "state" / f"{source_id}.json"

    def snapshot_path(self, source_id: str) -> Path:
        return self.root / "manifests" / "source-manifests" / f"{source_id}.json"

    def checkpoint_path(self, source_id: str) -> Path:
        return self.root / "checkpoints" / f"{source_id}.json"

    def load_records(self, source_id: str) -> list[RecordProvenance]:
        payload = read_json(self.state_path(source_id), [])
        if not isinstance(payload, list):
            raise ValueError(f"state for {source_id} is not a list")
        records: list[RecordProvenance] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError(f"state for {source_id} contains a non-object")
            model = RECORD_MODELS.get(str(item.get("record_type")))
            if model is None:
                raise ValueError(f"state for {source_id} contains an unsupported record type")
            records.append(model.model_validate(item))
        return records

    def write_records(self, source_id: str, records: list[RecordProvenance]) -> None:
        atomic_write_json(self.state_path(source_id), records)

    def load_snapshot(self, source_id: str) -> SourceSnapshot | None:
        payload = read_json(self.snapshot_path(source_id))
        return SourceSnapshot.model_validate(payload) if payload else None

    def write_snapshot(self, snapshot: SourceSnapshot) -> None:
        atomic_write_json(self.snapshot_path(snapshot.source_id), snapshot)

    def load_events(self) -> list[NotificationChange]:
        payload = read_json(self.root / "events" / "notification-events.json", [])
        return [NotificationChange.model_validate(item) for item in payload]

    def append_events(self, incoming: list[NotificationChange]) -> int:
        events = self.load_events()
        existing_ids = {event.event_id for event in events}
        added = [event for event in incoming if event.event_id not in existing_ids]
        if added:
            events.extend(added)
            events.sort(key=lambda event: (event.first_observed_time, event.event_id))
            atomic_write_json(self.root / "events" / "notification-events.json", events)
        return len(added)

    def write_checkpoint(self, checkpoint: UpdateCheckpoint) -> None:
        atomic_write_json(self.checkpoint_path(checkpoint.source_id), checkpoint)

    def load_checkpoint(self, source_id: str) -> UpdateCheckpoint | None:
        payload = read_json(self.checkpoint_path(source_id))
        return UpdateCheckpoint.model_validate(payload) if payload else None

    def source_ids(self) -> list[str]:
        state_root = self.root / "state"
        return (
            sorted(path.stem for path in state_root.glob("*.json")) if state_root.exists() else []
        )

    def all_snapshots(self) -> list[SourceSnapshot]:
        snapshots = [
            snapshot
            for source_id in self.source_ids()
            if (snapshot := self.load_snapshot(source_id)) is not None
        ]
        return sorted(snapshots, key=lambda snapshot: snapshot.source_id)

    def inventory(self) -> dict[str, Any]:
        return {
            "dataset_class": self.dataset_class(),
            "sources": {
                source_id: len(self.load_records(source_id)) for source_id in self.source_ids()
            },
            "events": len(self.load_events()),
        }
