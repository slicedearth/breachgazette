"""Source-drift thresholds and non-sensitive private-state health reports."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from breachgazette.contracts import (
    MonitoringCatalogue,
    SourceHealthEntry,
    SourceHealthReport,
    SourceMonitoringPolicy,
)
from breachgazette.policies import load_source_policies, repository_root
from breachgazette.state import PrivateStateStore
from breachgazette.utils import atomic_write_json, read_json


class SourceDriftError(RuntimeError):
    """Raised before a suspicious source result can replace prior complete state."""


def load_monitoring_catalogue(path: Path | None = None) -> MonitoringCatalogue:
    catalogue_path = path or repository_root() / "sources" / "monitoring.json"
    payload = read_json(catalogue_path)
    if not isinstance(payload, dict):
        raise ValueError("source monitoring catalogue is missing or invalid")
    catalogue = MonitoringCatalogue.model_validate(payload)
    policies = load_source_policies()
    implemented_sources = {
        source_id for source_id, policy in policies.items() if policy.implemented
    }
    if set(catalogue.sources) != implemented_sources:
        raise ValueError("source monitoring catalogue must cover every implemented source exactly")
    for source_id, policy in catalogue.sources.items():
        if policy.source_id != source_id:
            raise ValueError(f"monitoring policy key does not match source_id: {source_id}")
    return catalogue


def guard_source_record_count(
    source_id: str,
    *,
    previous_count: int,
    incoming_count: int,
    policy: SourceMonitoringPolicy | None = None,
) -> None:
    threshold = policy or load_monitoring_catalogue().sources[source_id]
    if incoming_count < threshold.minimum_records:
        raise SourceDriftError(
            f"{source_id} returned {incoming_count} records, below its reviewed floor"
        )
    if previous_count == 0:
        return
    retained_fraction = incoming_count / previous_count
    growth_factor = incoming_count / previous_count
    if retained_fraction < threshold.minimum_retained_fraction:
        raise SourceDriftError(
            f"{source_id} retained too few records relative to its previous complete state"
        )
    if growth_factor > threshold.maximum_growth_factor:
        raise SourceDriftError(f"{source_id} grew beyond its reviewed change threshold")


def build_source_health_report(
    *,
    data_root: Path,
    generated_at: datetime | None = None,
) -> SourceHealthReport:
    now = generated_at or datetime.now(UTC)
    store = PrivateStateStore(data_root)
    catalogue = load_monitoring_catalogue()
    entries: list[SourceHealthEntry] = []
    for source_id, policy in sorted(catalogue.sources.items()):
        snapshot = store.load_snapshot(source_id)
        checkpoint = store.load_checkpoint(source_id)
        records = store.load_records(source_id)
        reasons: list[str] = []
        age_hours: float | None = None
        status = "healthy"
        if snapshot is None:
            status = "missing"
            reasons.append("No complete source snapshot is stored.")
        else:
            age_hours = max(0.0, (now - snapshot.completed_at).total_seconds() / 3_600)
            if snapshot.stale or age_hours > policy.stale_after_hours:
                status = "stale"
                reasons.append("The latest complete snapshot exceeds its freshness threshold.")
            if len(records) < policy.minimum_records:
                status = "record_count_below_floor"
                reasons.append("The stored record count is below its reviewed source floor.")
        if checkpoint is not None and checkpoint.status == "failed":
            status = "failed_update"
            reasons.append("The latest bounded update attempt failed; prior state was preserved.")
        elif checkpoint is not None and checkpoint.status == "in_progress":
            status = "incomplete_update"
            reasons.append("The latest bounded update did not reach a terminal checkpoint.")
        entries.append(
            SourceHealthEntry(
                source_id=source_id,
                status=status,
                record_count=len(records),
                minimum_records=policy.minimum_records,
                completeness=snapshot.completeness if snapshot else None,
                snapshot_checksum=snapshot.checksum_sha256 if snapshot else None,
                snapshot_age_hours=round(age_hours, 2) if age_hours is not None else None,
                stale_after_hours=policy.stale_after_hours,
                latest_attempted_update=(
                    checkpoint.attempted_at
                    if checkpoint
                    else snapshot.latest_attempted_update
                    if snapshot
                    else None
                ),
                last_successful_update=(
                    snapshot.last_successful_complete_update or snapshot.completed_at
                    if snapshot
                    else None
                ),
                checkpoint_status=checkpoint.status if checkpoint else "missing",
                reasons=reasons,
            )
        )
    dataset_class = store.dataset_class() or "unknown"
    return SourceHealthReport(
        generated_at=now,
        dataset_class=dataset_class,
        passed=dataset_class == "real_source_data"
        and all(entry.status == "healthy" for entry in entries),
        schedule_utc=catalogue.schedule_utc,
        sources=entries,
        limitations=[
            "Health states describe retrieval freshness and contract checks, not whether an "
            "underlying official source is factually complete.",
            "A failed update preserves the preceding complete source state.",
        ],
    )


def write_source_health_report(report: SourceHealthReport, output: Path) -> None:
    atomic_write_json(output, report)
