"""Reviewed breach-related regulatory decisions from fixed official publications."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import httpx
import yaml
from pydantic import Field, HttpUrl, ValidationError

from breachgazette.clients.base import (
    AdapterResult,
    BoundedSourceClient,
    SourceClientError,
    source_snapshot,
)
from breachgazette.clients.netherlands_ap import _visible_text
from breachgazette.contracts import OrganizationRole, SourceRegulatoryRecord
from breachgazette.contracts.enums import Completeness, EntityRole, LegalStatus, ValueOrigin
from breachgazette.contracts.models import ContractModel, RecordProvenance
from breachgazette.policies import repository_root
from breachgazette.utils import (
    canonical_json_bytes,
    normalize_organization_name,
    normalize_text,
    sha256_hex,
)


class ReviewedDecision(ContractModel):
    event_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,150}$")
    matter_id: str = Field(min_length=1, max_length=200)
    entity: str = Field(min_length=1, max_length=500)
    official_url: HttpUrl
    expected_markers: list[str] = Field(min_length=3, max_length=8)
    source_title: str = Field(min_length=1, max_length=500)
    publication_date: date
    event_date: date
    legal_status: Literal["administrative_fine"]
    status_wording: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=1200)


class DecisionManifest(ContractModel):
    schema_version: Literal["1.0"]
    source_id: str
    reviewed_at: date
    entries: list[ReviewedDecision] = Field(min_length=1, max_length=100)


class EuropeanRegulatoryAdapter:
    adapter_version = "1.0"
    normalization_version = "1.0"
    max_records = 100
    source_id: str
    regulator: str
    origin: str
    path_prefix: str

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self.transport = transport
        self.manifest_path = manifest_path or (
            repository_root() / "sources" / f"{self.source_id.replace('_', '-')}.yml"
        )

    def collect(self, *, observed_at: datetime | None = None) -> AdapterResult:
        observed_at = observed_at or datetime.now(UTC)
        if self.manifest_path.stat().st_size > 1_000_000:
            raise SourceClientError("regulatory manifest exceeds its byte bound")
        try:
            manifest = DecisionManifest.model_validate(
                yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
            )
        except (ValidationError, yaml.YAMLError) as exc:
            raise SourceClientError("regulatory manifest is invalid") from exc
        entries = manifest.entries
        if (
            manifest.source_id != self.source_id
            or manifest.reviewed_at > observed_at.date()
            or len({entry.event_id for entry in entries}) != len(entries)
            or any(
                entry.publication_date > manifest.reviewed_at
                or entry.event_date > entry.publication_date
                or not entry.event_id.startswith(self.source_id.replace("_", "-") + "-")
                or any(not marker.strip() or len(marker) > 300 for marker in entry.expected_markers)
                for entry in entries
            )
        ):
            raise SourceClientError("regulatory manifest identities or dates are inconsistent")
        pages: dict[str, tuple[str, str]] = {}
        with BoundedSourceClient(
            allowed_origins={self.origin},
            allowed_path_prefixes=(self.path_prefix,),
            max_response_bytes=2_000_000,
            total_deadline_seconds=180,
            transport=self.transport,
        ) as client:
            for entry in entries:
                url = str(entry.official_url)
                if url not in pages:
                    content, _headers, _final_url = client.get_text(url)
                    pages[url] = (_visible_text(content).casefold(), sha256_hex(content))
                text, _checksum = pages[url]
                if not all(
                    normalize_text(marker).casefold() in text for marker in entry.expected_markers
                ):
                    raise SourceClientError("reviewed regulatory source markers changed")
        records: list[RecordProvenance] = []
        for entry in entries:
            checksum = pages[str(entry.official_url)][1]
            records.append(
                SourceRegulatoryRecord(
                    source_id=self.source_id,
                    source_record_id=entry.event_id,
                    source_url=entry.official_url,
                    source_revision=checksum[:16],
                    source_checksum=checksum,
                    source_completeness=Completeness.SELECTIVE,
                    source_retrieval_time=observed_at,
                    local_first_observed_time=observed_at,
                    local_last_observed_time=observed_at,
                    parser_version=self.adapter_version,
                    normalization_version=self.normalization_version,
                    limitations=[
                        "Selected official decisions, not a complete enforcement register.",
                        "A regulator-issued fine is not a court judgment. Later appeals, "
                        "variations or payments are not inferred from this event.",
                    ],
                    regulator=self.regulator,
                    matter_id=entry.matter_id,
                    entity=OrganizationRole(
                        source_name=entry.entity,
                        normalized_name=normalize_organization_name(entry.entity),
                        role=EntityRole.REGULATOR_NAMED_ENTITY,
                        origin=ValueOrigin.MANUALLY_CURATED,
                    ),
                    legal_status=LegalStatus.ADMINISTRATIVE_FINE,
                    source_title=entry.source_title,
                    source_publication_date=entry.publication_date,
                    source_reported_event_date=entry.event_date,
                    status_wording=entry.status_wording,
                    summary=entry.summary,
                    allegation=False,
                    finding=True,
                )
            )
        checksum = sha256_hex(
            canonical_json_bytes(
                {
                    "manifest": manifest.model_dump(mode="json"),
                    "pages": {url: checksum for url, (_text, checksum) in sorted(pages.items())},
                }
            )
        )
        return AdapterResult(
            source_id=self.source_id,
            records=records,
            snapshot=source_snapshot(
                source_id=self.source_id,
                retrieved_at=observed_at,
                revision=f"manifest:{manifest.reviewed_at}:{checksum[:12]}",
                checksum=checksum,
                completeness=Completeness.SELECTIVE,
                discovered=len(entries),
                accepted=len(records),
                rejected=0,
                bounded_limit=self.max_records,
                notes=[
                    "Dates, entities and decision markers are checked against official pages.",
                    "New matters and later legal outcomes require a reviewed manifest change.",
                ],
            ),
        )


class UnitedKingdomRegulatoryAdapter(EuropeanRegulatoryAdapter):
    source_id = "united_kingdom_ico_regulatory"
    regulator = "Information Commissioner's Office"
    origin = "https://ico.org.uk"
    path_prefix = "/action-weve-taken/enforcement/"


class FranceRegulatoryAdapter(EuropeanRegulatoryAdapter):
    source_id = "france_cnil_regulatory"
    regulator = "Commission nationale de l'informatique et des libertés"
    origin = "https://www.cnil.fr"
    path_prefix = "/fr/"
