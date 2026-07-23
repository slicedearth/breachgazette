"""Build real-source publication assets without writing production data into Git."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from breachgazette.contracts import (
    NormalizedNotification,
    PublicationManifest,
    QualityReport,
    RegulatoryAction,
    SourceAggregateRecord,
    SourceNotificationRecord,
)
from breachgazette.entities import load_alias_catalogue, resolve_organizations
from breachgazette.monitoring import build_source_health_report
from breachgazette.policies import load_source_policies
from breachgazette.privacy.audit import require_public_safe
from breachgazette.quality import DataQualityError, build_quality_report
from breachgazette.relationships import generate_candidates
from breachgazette.state import PrivateStateStore
from breachgazette.utils import atomic_write_json, sha256_hex

DETAIL_RECORDS_PER_SOURCE = 250
LATEST_RECORDS = 100
SEARCH_PARTITION_SIZE = 250


def _latest_date(record: SourceNotificationRecord) -> str:
    dates = [
        observation.normalized_date.isoformat()
        for observation in record.dates
        if observation.normalized_date is not None
    ]
    return max(dates, default="0001-01-01")


def _search_year(record: NormalizedNotification) -> str:
    normalized_dates = sorted(
        observation.normalized_date
        for observation in record.dates
        if observation.normalized_date is not None
    )
    return str(normalized_dates[-1].year) if normalized_dates else "unknown"


def _population_band(record: NormalizedNotification) -> str:
    count = record.affected_population.count if record.affected_population else None
    if count is None:
        return "not_published"
    if count < 1_000:
        return "500_999"
    if count < 10_000:
        return "1000_9999"
    if count < 100_000:
        return "10000_99999"
    return "100000_plus"


def _search_facets(records: list[NormalizedNotification]) -> dict[str, list[str]]:
    return {
        "jurisdictions": sorted({record.jurisdiction for record in records}),
        "regulators": sorted({record.regulator for record in records}),
        "sources": sorted({record.source_id for record in records}),
        "years": sorted({_search_year(record) for record in records}, reverse=True),
        "causes": sorted(
            {
                record.breach_cause.normalized_label
                for record in records
                if record.breach_cause and record.breach_cause.normalized_label
            }
        ),
        "information_categories": sorted(
            {
                category.normalized_label
                for record in records
                for category in record.information_categories
            }
        ),
        "population_bands": sorted({_population_band(record) for record in records}),
        "roles": sorted({record.named_entity.role for record in records}),
        "publication_levels": sorted({record.publication_level for record in records}),
    }


def _build_search_assets(
    records: list[NormalizedNotification],
    *,
    detail_ids: set[str],
    generated_at: datetime,
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    grouped: dict[tuple[str, str], list[NormalizedNotification]] = defaultdict(list)
    for record in records:
        grouped[(record.source_id, _search_year(record))].append(record)
    partitions: list[tuple[str, dict[str, Any]]] = []
    partition_metadata: list[dict[str, Any]] = []
    for (source_id, year), group in sorted(grouped.items()):
        ordered = sorted(
            group,
            key=lambda record: (_latest_date(record), record.source_record_id),
            reverse=True,
        )
        for offset in range(0, len(ordered), SEARCH_PARTITION_SIZE):
            page = offset // SEARCH_PARTITION_SIZE + 1
            partition_id = f"{source_id}-{year}-{page:03d}"
            partition_records = ordered[offset : offset + SEARCH_PARTITION_SIZE]
            facets = _search_facets(partition_records)
            payload_records = []
            for record in partition_records:
                payload = record.model_dump(mode="json")
                payload["has_detail_page"] = record.source_record_id in detail_ids
                payload_records.append(payload)
            payload = {
                "schema_version": "1.0",
                "partition_id": partition_id,
                "records": payload_records,
            }
            partitions.append((partition_id, payload))
            partition_metadata.append(
                {
                    "id": partition_id,
                    "count": len(partition_records),
                    **facets,
                }
            )
    manifest = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "record_count": len(records),
        "partition_size": SEARCH_PARTITION_SIZE,
        "facets": _search_facets(records),
        "partitions": partition_metadata,
    }
    return manifest, partitions


def build_site_data(*, data_root: Path, output: Path) -> dict[str, Any]:
    store = PrivateStateStore(data_root)
    if store.dataset_class() != "real_source_data":
        raise DataQualityError("production site data requires real source-derived state")
    generated_at = datetime.now(UTC)
    source_health = build_source_health_report(data_root=data_root, generated_at=generated_at)
    if not source_health.passed:
        failed = ", ".join(
            f"{entry.source_id}:{entry.status}"
            for entry in source_health.sources
            if entry.status != "healthy"
        )
        raise DataQualityError(f"production source health gates failed: {failed}")
    health_states: dict[str, str] = {
        entry.source_id: entry.status for entry in source_health.sources
    }
    records_by_source = {
        source_id: store.load_records(source_id) for source_id in store.source_ids()
    }
    snapshots = store.all_snapshots()
    initial_quality = build_quality_report(
        dataset_class="real_source_data",
        records_by_source=records_by_source,
        snapshots=snapshots,
        source_health=health_states,
    )
    aggregates = [
        SourceAggregateRecord.model_validate(record.model_dump(mode="json"))
        for records in records_by_source.values()
        for record in records
        if getattr(record, "record_type", None) == "aggregate"
    ]
    notifications = [
        NormalizedNotification.model_validate(record.model_dump(mode="json"))
        for records in records_by_source.values()
        for record in records
        if getattr(record, "record_type", None) == "notification"
    ]
    regulatory_actions = [
        RegulatoryAction.model_validate(record.model_dump(mode="json"))
        for records in records_by_source.values()
        for record in records
        if getattr(record, "record_type", None) == "regulatory"
    ]
    organizations = resolve_organizations(
        notifications,
        regulatory_actions,
        alias_catalogue=load_alias_catalogue(),
    )
    organization_by_alias = {
        alias.normalized_name: identity.organization_id
        for identity in organizations
        for alias in identity.aliases
    }
    for notification in notifications:
        notification.canonical_organization_id = organization_by_alias.get(
            notification.named_entity.normalized_name
        )
    for action in regulatory_actions:
        action.canonical_organization_id = organization_by_alias.get(action.entity.normalized_name)
    relationships = generate_candidates(notifications)
    events = [
        event for event in store.load_events() if event.event_type != "notification_first_observed"
    ]
    policies = load_source_policies()
    ordered_notifications = sorted(
        notifications,
        key=lambda record: (_latest_date(record), record.source_record_id),
        reverse=True,
    )
    detail_ids: set[str] = set()
    for source_id in sorted({record.source_id for record in notifications}):
        source_records = [
            record for record in ordered_notifications if record.source_id == source_id
        ]
        detail_ids.update(
            record.source_record_id for record in source_records[:DETAIL_RECORDS_PER_SOURCE]
        )
    detail_notifications = [
        record for record in ordered_notifications if record.source_record_id in detail_ids
    ]
    detail_org_ids = {
        record.canonical_organization_id
        for record in detail_notifications
        if record.canonical_organization_id
    } | {
        action.canonical_organization_id
        for action in regulatory_actions
        if action.canonical_organization_id
    }
    detail_organizations = [
        identity for identity in organizations if identity.organization_id in detail_org_ids
    ]
    summary_payload = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "tagline": "Public breach notifications, connected and explained.",
        "disclaimer": (
            "Breach Gazette reproduces or derives information from official public sources "
            "and does not independently verify the underlying events."
        ),
        "policies": policies,
        "snapshots": snapshots,
        "stats": {
            "aggregate_metrics": len(aggregates),
            "public_notifications": len(notifications),
            "regulatory_actions": len(regulatory_actions),
            "organizations": len(organizations),
            "relationship_candidates": len(relationships),
            "corrections": len(events),
        },
        "latest_notifications": ordered_notifications[:LATEST_RECORDS],
        "detail_notifications": detail_notifications,
        "aggregates": aggregates,
        "regulatory_actions": regulatory_actions,
        "detail_organizations": detail_organizations,
        "relationships": relationships,
        "corrections": sorted(
            events,
            key=lambda event: (event.first_observed_time, event.event_id),
            reverse=True,
        )[:250],
        "quality": initial_quality,
        "source_health": source_health,
        "deferred_sources": [policy for policy in policies.values() if not policy.implemented],
    }
    require_public_safe(summary_payload, record_identity="publication-summary")
    search_manifest, search_partitions = _build_search_assets(
        ordered_notifications,
        detail_ids=detail_ids,
        generated_at=generated_at,
    )
    require_public_safe(search_manifest, record_identity="notification-search-manifest")
    publication_checksum = sha256_hex(summary_payload)
    manifest = PublicationManifest(
        generated_at=generated_at,
        dataset_class="real_source_data",
        record_counts={
            "aggregate_metrics": len(aggregates),
            "notifications": len(notifications),
            "regulatory_actions": len(regulatory_actions),
            "organizations": len(organizations),
            "relationships": len(relationships),
            "corrections": len(events),
        },
        source_snapshots=snapshots,
        publication_checksum=publication_checksum,
        max_public_records=len(notifications),
        limitations=[
            "Incident relationships are candidates, not confirmed incident merges.",
            "Aggregate metrics remain separate from named notifications.",
            "Static detail pages are bounded to the latest 250 records per incident source.",
        ],
    )
    summary_payload["manifest"] = manifest
    final_quality: QualityReport = build_quality_report(
        dataset_class="real_source_data",
        records_by_source=records_by_source,
        snapshots=snapshots,
        public_payloads=[
            summary_payload,
            notifications,
            organizations,
            relationships,
            search_manifest,
        ],
        source_health=health_states,
    )
    summary_payload["quality"] = final_quality
    output.mkdir(parents=True, exist_ok=True)
    search_output = output / "search-partitions"
    search_output.mkdir(parents=True, exist_ok=True)
    for existing in search_output.glob("*.json"):
        existing.unlink()
    for partition_id, payload in search_partitions:
        atomic_write_json(search_output / f"{partition_id}.json", payload)
    atomic_write_json(output / "publication.json", summary_payload)
    atomic_write_json(output / "notifications.json", notifications)
    atomic_write_json(output / "search-manifest.json", search_manifest)
    atomic_write_json(output / "source-health.json", source_health)
    atomic_write_json(output / "organizations.json", organizations)
    atomic_write_json(output / "relationships.json", relationships)
    atomic_write_json(output / "quality-report.json", final_quality)
    atomic_write_json(output / "publication-manifest.json", manifest)
    return {
        "output": str(output),
        "publication_checksum": publication_checksum,
        "records": manifest.record_counts,
        "search_partitions": len(search_partitions),
        "quality_passed": final_quality.passed,
    }


def audit_public_tree(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_dir():
        raise ValueError("public tree does not exist")
    forbidden = (
        "tests/fixtures",
        'dataset_class":"test_fixture',
        '<script src="http',
        "google-analytics",
        "googletagmanager",
    )
    scanned_files = 0
    scanned_bytes = 0
    violations: list[str] = []
    for file in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        size = file.stat().st_size
        scanned_files += 1
        scanned_bytes += size
        if size > 15_000_000:
            violations.append(f"{file}: file exceeds 15 MB")
            continue
        if file.suffix.lower() not in {
            ".html",
            ".css",
            ".js",
            ".json",
            ".xml",
            ".txt",
            ".csv",
            ".svg",
        }:
            continue
        text = file.read_text(encoding="utf-8", errors="replace").casefold()
        for marker in forbidden:
            if marker.casefold() in text:
                violations.append(f"{file}: forbidden marker {marker}")
    if violations:
        raise DataQualityError("public tree audit failed: " + "; ".join(violations[:10]))
    return {
        "path": str(path),
        "files": scanned_files,
        "bytes": scanned_bytes,
        "passed": True,
    }
