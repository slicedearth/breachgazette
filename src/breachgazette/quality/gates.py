"""Fail-closed quality checks for normalized and public data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from breachgazette.contracts import QualityReport, SourceSnapshot
from breachgazette.contracts.models import RecordProvenance
from breachgazette.privacy.audit import audit_public_value

REQUIRED_SOURCES = {
    "oaic_ndb",
    "nsw_public_notifications",
    "nsw_mndb_aggregate",
    "oaic_regulatory",
    "washington",
    "california",
    "massachusetts",
}


class DataQualityError(RuntimeError):
    """Raised when publication cannot safely continue."""


def build_quality_report(
    *,
    dataset_class: str,
    records_by_source: dict[str, list[RecordProvenance]],
    snapshots: list[SourceSnapshot],
    public_payloads: list[Any] | None = None,
    source_health: dict[str, str] | None = None,
) -> QualityReport:
    if dataset_class not in {"real_source_data", "test_fixture"}:
        raise DataQualityError("dataset class is absent or unsupported")
    source_ids = set(records_by_source)
    required_present = source_ids >= REQUIRED_SOURCES
    nonempty = all(records_by_source.get(source_id) for source_id in REQUIRED_SOURCES & source_ids)
    snapshot_by_source = {snapshot.source_id: snapshot for snapshot in snapshots}
    snapshots_present = set(snapshot_by_source) >= REQUIRED_SOURCES
    attribution_present = all(snapshot.revision for snapshot in snapshots)
    no_rejections = all(snapshot.records_rejected == 0 for snapshot in snapshots)
    legal_status_explicit = all(
        getattr(record, "legal_status", None) != "status_unknown"
        for records in records_by_source.values()
        for record in records
        if getattr(record, "record_type", None) == "regulatory"
    )
    fixture_isolation = dataset_class == "real_source_data"
    findings = []
    for source_id, records in records_by_source.items():
        for record in records:
            findings.extend(
                audit_public_value(record, record_identity=f"{source_id}:{record.source_record_id}")
            )
    for index, payload in enumerate(public_payloads or []):
        findings.extend(audit_public_value(payload, record_identity=f"publication-payload:{index}"))
    checks = {
        "required_sources_present": required_present,
        "required_sources_nonempty": nonempty,
        "source_snapshots_present": snapshots_present,
        "source_attribution_present": attribution_present,
        "no_source_rejections": no_rejections,
        "legal_status_explicit": legal_status_explicit,
        "privacy_audit_passed": not findings,
        "fixture_isolation": fixture_isolation,
    }
    if source_health is not None:
        checks["source_health_passed"] = all(
            status == "healthy" for status in source_health.values()
        )
    passed = all(checks.values())
    report = QualityReport(
        generated_at=datetime.now(UTC),
        passed=passed,
        dataset_class=dataset_class,
        source_health=source_health
        or {
            source_id: (
                "stale"
                if snapshot_by_source.get(source_id) and snapshot_by_source[source_id].stale
                else "complete"
                if source_id in snapshot_by_source
                else "missing"
            )
            for source_id in sorted(REQUIRED_SOURCES | source_ids)
        },
        checks=checks,
        findings=findings,
        record_counts={
            source_id: len(records) for source_id, records in sorted(records_by_source.items())
        },
        limitations=[
            "Quality gates validate publication contracts, not the underlying reported events.",
            "A passing report does not establish source completeness beyond each source policy.",
        ],
    )
    if not passed:
        failed = ", ".join(name for name, result in checks.items() if not result)
        finding_summary = ", ".join(
            f"{finding.detector_id}@{finding.field}" for finding in findings[:5]
        )
        suffix = f" ({finding_summary})" if finding_summary else ""
        raise DataQualityError(f"publication quality gates failed: {failed}{suffix}")
    return report
