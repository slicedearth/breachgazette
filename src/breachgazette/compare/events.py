"""Compare current and previous normalized source records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from breachgazette.contracts import NotificationChange
from breachgazette.contracts.enums import Completeness
from breachgazette.contracts.models import RecordProvenance
from breachgazette.utils import canonical_data, sha256_hex

PROVENANCE_FIELDS = frozenset(RecordProvenance.model_fields)


def _comparable(record: RecordProvenance | dict[str, Any]) -> dict[str, Any]:
    payload = canonical_data(record)
    return {key: value for key, value in payload.items() if key not in PROVENANCE_FIELDS}


def compare_records(
    previous: dict[str, RecordProvenance],
    current: dict[str, RecordProvenance],
    *,
    source_id: str,
    current_snapshot: str,
    previous_snapshot: str | None,
    observed_at: datetime,
    completeness: Completeness,
) -> list[NotificationChange]:
    events: list[NotificationChange] = []
    for record_id in sorted(current):
        current_value = _comparable(current[record_id])
        if record_id not in previous:
            event_type = "notification_first_observed"
            before_value = None
            after_value: Any = {
                "source_record_id": record_id,
                "source_checksum": canonical_data(current[record_id]).get(
                    "source_checksum"
                ),
            }
            reason = "The source record was not present in the previous comparable snapshot."
        else:
            previous_value = _comparable(previous[record_id])
            if previous_value == current_value:
                continue
            event_type = "source_record_corrected"
            before_value = previous_value
            after_value = current_value
            reason = "The normalized source record changed between comparable snapshots."
        seed = [
            "1.0",
            source_id,
            record_id,
            event_type,
            before_value,
            after_value,
            previous_snapshot,
            current_snapshot,
        ]
        events.append(
            NotificationChange(
                event_id=sha256_hex(seed),
                source_id=source_id,
                record_id=record_id,
                event_type=event_type,
                before_value=before_value,
                after_value=after_value,
                reason=reason,
                previous_snapshot=previous_snapshot,
                current_snapshot=current_snapshot,
                source_completeness=completeness,
                detector_version="1.0",
                first_observed_time=observed_at,
                limitations=[],
            )
        )
    if completeness == Completeness.COMPLETE:
        for record_id in sorted(previous.keys() - current.keys()):
            previous_value = _comparable(previous[record_id])
            seed = [
                "1.0",
                source_id,
                record_id,
                "source_status_changed",
                previous_value,
                None,
                previous_snapshot,
                current_snapshot,
            ]
            events.append(
                NotificationChange(
                    event_id=sha256_hex(seed),
                    source_id=source_id,
                    record_id=record_id,
                    event_type="source_status_changed",
                    before_value=previous_value,
                    after_value=None,
                    reason="The record was absent from a complete current snapshot.",
                    previous_snapshot=previous_snapshot,
                    current_snapshot=current_snapshot,
                    source_completeness=completeness,
                    detector_version="1.0",
                    first_observed_time=observed_at,
                    limitations=[
                        "Absence may reflect a source correction and is not evidence of "
                        "remediation."
                    ],
                )
            )
    return events
