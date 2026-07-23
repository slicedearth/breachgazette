"""Curated, source-verified OAIC regulatory action adapter."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import yaml

from breachgazette.clients.base import (
    AdapterResult,
    BoundedSourceClient,
    SourceClientError,
    source_snapshot,
)
from breachgazette.contracts import OrganizationRole, SourceRegulatoryRecord
from breachgazette.contracts.enums import (
    Completeness,
    EntityRole,
    LegalStatus,
    ValueOrigin,
)
from breachgazette.contracts.models import RecordProvenance
from breachgazette.policies import repository_root
from breachgazette.utils import canonical_json_bytes, normalize_organization_name, sha256_hex


class OaicRegulatoryAdapter:
    source_id = "oaic_regulatory"
    adapter_version = "1.0"
    normalization_version = "1.0"
    max_records = 100

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self.transport = transport
        self.manifest_path = (
            manifest_path or repository_root() / "sources" / "oaic-regulatory-actions.yml"
        )

    def collect(self, *, observed_at: datetime | None = None) -> AdapterResult:
        observed_at = observed_at or datetime.now(UTC)
        manifest = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != "1.0":
            raise SourceClientError("OAIC regulatory manifest version is unsupported")
        entries = manifest.get("entries")
        if not isinstance(entries, list) or not entries or len(entries) > self.max_records:
            raise SourceClientError("OAIC regulatory manifest was empty or exceeded its bound")
        page_checksums: dict[str, str] = {}
        with BoundedSourceClient(
            allowed_origins={"https://www.oaic.gov.au"},
            allowed_path_prefixes=(
                "/news/media-centre/",
                "/privacy/privacy-assessments-and-decisions/",
            ),
            max_response_bytes=3_000_000,
            total_deadline_seconds=180,
            transport=self.transport,
        ) as client:
            for entry in entries:
                url = str(entry["official_url"])
                if url not in page_checksums:
                    html, _headers, _url = client.get_text(url)
                    page_checksums[url] = sha256_hex(html)
                else:
                    html = ""
                marker = str(entry["expected_marker"])
                if html:
                    marker_present = marker.casefold() in html.casefold()
                else:
                    # A repeated URL was already checked; fetch-free verification uses the
                    # first entry's exact same reviewed page checksum.
                    first = next(item for item in entries if item["official_url"] == url)
                    marker_present = (
                        marker == first["expected_marker"]
                        or marker.casefold() in client.get_text(url)[0].casefold()
                    )
                if not marker_present:
                    raise SourceClientError("OAIC curated source marker changed")

        record_checksum = sha256_hex(canonical_json_bytes(entries))
        records: list[RecordProvenance] = []
        for entry in entries:
            status = LegalStatus(str(entry["legal_status"]))
            role = EntityRole(str(entry["entity_role"]))
            page_checksum = page_checksums[str(entry["official_url"])]
            allegation = status in {
                LegalStatus.CIVIL_PROCEEDING_FILED,
                LegalStatus.CIVIL_PROCEEDING_ALLEGATION,
            }
            finding = status in {
                LegalStatus.DETERMINATION_MADE,
                LegalStatus.COURT_JUDGMENT,
                LegalStatus.CIVIL_PENALTY_ORDER,
            }
            records.append(
                SourceRegulatoryRecord(
                    source_id=self.source_id,
                    source_record_id=str(entry["event_id"]),
                    source_url=str(entry["official_url"]),
                    source_revision=page_checksum[:16],
                    source_checksum=page_checksum,
                    source_completeness=Completeness.SELECTIVE,
                    source_retrieval_time=observed_at,
                    local_first_observed_time=observed_at,
                    local_last_observed_time=observed_at,
                    parser_version=self.adapter_version,
                    normalization_version=self.normalization_version,
                    limitations=["The timeline is curated and selective rather than exhaustive."],
                    regulator="Office of the Australian Information Commissioner",
                    matter_id=str(entry["matter_id"]),
                    entity=OrganizationRole(
                        source_name=str(entry["entity"]),
                        normalized_name=normalize_organization_name(str(entry["entity"])),
                        role=role,
                        origin=ValueOrigin.MANUALLY_CURATED,
                    ),
                    legal_status=status,
                    source_title=str(entry["source_title"]),
                    source_publication_date=date.fromisoformat(str(entry["publication_date"])),
                    source_reported_event_date=date.fromisoformat(str(entry["event_date"])),
                    status_wording=str(entry["status_wording"]),
                    summary=str(entry["summary"]),
                    previous_related_event=entry.get("previous_related_event"),
                    allegation=allegation,
                    finding=finding,
                )
            )
        snapshot = source_snapshot(
            source_id=self.source_id,
            retrieved_at=observed_at,
            revision=f"manifest:{manifest['reviewed_at']}:{record_checksum[:12]}",
            checksum=record_checksum,
            completeness=Completeness.SELECTIVE,
            discovered=len(entries),
            accepted=len(records),
            rejected=0,
            bounded_limit=self.max_records,
            notes=[
                "Every entry is manually reviewed and tied to a fixed official OAIC URL.",
                "Allegations, findings, undertakings, and no-adverse outcomes remain distinct.",
            ],
        )
        return AdapterResult(source_id=self.source_id, records=records, snapshot=snapshot)
