"""Fixed annual headline statistics, not inferred totals from notification rows."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import ClassVar

import httpx

from breachgazette.clients.base import (
    AdapterResult,
    BoundedSourceClient,
    SourceClientError,
    source_snapshot,
)
from breachgazette.clients.netherlands_ap import _visible_text
from breachgazette.contracts import SourceAggregateRecord
from breachgazette.contracts.enums import Completeness, PublicationLevel, ValueOrigin
from breachgazette.contracts.models import ObservedValue
from breachgazette.utils import sha256_hex


class AnnualReportAdapter:
    adapter_version = "1.0"
    normalization_version = "1.0"
    max_records = 1
    source_id: str
    report_url: str
    origin: str
    path: str
    title_marker: str
    pattern: str
    record_id: str
    regulator: str
    category: str
    dimension: str
    population_scope: str
    notes: ClassVar[list[str]]
    published: datetime
    reviewed_value: int | None = None

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def collect(self, *, observed_at: datetime | None = None) -> AdapterResult:
        observed_at = observed_at or datetime.now(UTC)
        with BoundedSourceClient(
            allowed_origins={self.origin},
            allowed_path_prefixes=(self.path,),
            max_response_bytes=1_000_000,
            transport=self.transport,
        ) as client:
            content, _headers, _final_url = client.get_text(self.report_url)
        text = _visible_text(content)
        matches = re.findall(self.pattern, text)
        if self.title_marker not in text or len(matches) != 1:
            raise SourceClientError("annual report headline markers changed or are ambiguous")
        raw_value = matches[0]
        value = int(re.sub(r"[ ,]", "", raw_value))
        if self.reviewed_value is not None and value != self.reviewed_value:
            raise SourceClientError(
                "adjusted annual headline changed; review its scope before reuse"
            )
        checksum = sha256_hex(content)
        revision = f"annual-report-2025:{checksum[:16]}"
        record = SourceAggregateRecord(
            source_id=self.source_id,
            source_record_id=self.record_id,
            source_url=self.report_url,
            source_revision=revision,
            source_checksum=checksum,
            source_completeness=Completeness.SELECTIVE,
            source_retrieval_time=observed_at,
            local_first_observed_time=observed_at,
            local_last_observed_time=observed_at,
            parser_version=self.adapter_version,
            normalization_version=self.normalization_version,
            limitations=[
                "One reviewed annual headline, not every measure in the annual report.",
                "Notification counts are not counts of unique real-world incidents.",
            ],
            regulator=self.regulator,
            reporting_scheme="GDPR personal data breach notifications",
            publication_level=PublicationLevel.NATIONAL_AGGREGATE,
            reporting_period_start=date(2025, 1, 1),
            reporting_period_end=date(2025, 12, 31),
            dimension=self.dimension,
            category=self.category,
            value=ObservedValue(
                value=value,
                origin=ValueOrigin.SOURCE_OBSERVED,
                source_label=raw_value,
            ),
            unit="notifications",
            population_scope=self.population_scope,
            source_notes=self.notes,
        )
        return AdapterResult(
            source_id=self.source_id,
            records=[record],
            snapshot=source_snapshot(
                source_id=self.source_id,
                retrieved_at=observed_at,
                revision=revision,
                checksum=checksum,
                completeness=Completeness.SELECTIVE,
                discovered=1,
                accepted=1,
                rejected=0,
                bounded_limit=self.max_records,
                source_updated_at=self.published,
                notes=self.notes,
            ),
        )


class IrelandDpcAdapter(AnnualReportAdapter):
    source_id = "ireland_dpc"
    origin = "https://dataprotection.ie"
    path = "/en/data-protection-commission-publishes-2025-annual-report"
    report_url = origin + path
    title_marker = "Data Protection Commission Publishes Annual Report for 2025"
    pattern = (
        r"Total valid breach notifications received in 2025 was "
        r"(\d{1,3}(?:,\d{3})*)\s*,?\s+representing"
    )
    record_id = "ie:dpc:valid_breach_notifications:2025"
    regulator = "Data Protection Commission"
    dimension = "valid_breach_notifications_received"
    category = "Valid breach notifications received"
    population_scope = "Valid notifications received by the Data Protection Commission in 2025"
    published = datetime(2026, 6, 30, tzinfo=UTC)
    notes: ClassVar[list[str]] = [
        "The annual report counts valid notifications, not all submissions or unique incidents.",
        "Source: Data Protection Commission, Annual Report 2025. Copyright DPC; reuse is "
        "subject to its public-sector information terms.",
    ]


class FranceCnilAnnualAdapter(AnnualReportAdapter):
    source_id = "france_cnil_annual"
    origin = "https://www.cnil.fr"
    path = "/fr/rapport-annuel-2025"
    report_url = origin + path
    title_marker = "le bilan et les actions marquantes de la CNIL en 2025"
    pattern = r"Parmi les (\d{1,3}(?: \d{3})*) violations de données notifiées à la CNIL,"
    record_id = "fr:cnil:adjusted_breach_notifications:2025"
    regulator = "Commission nationale de l'informatique et des libertés"
    dimension = "adjusted_breach_notifications_received"
    category = "Adjusted annual notification headline"
    population_scope = "CNIL annual headline excluding notifications from two major incidents"
    published = datetime(2026, 5, 18, tzinfo=UTC)
    reviewed_value = 6167
    notes: ClassVar[list[str]] = [
        "The annual report (page 52) excludes 11,635 notifications associated with two "
        "major incidents from 17,802 received, giving the published adjusted headline.",
        "This source-reported adjustment is not a deduplication performed by Breach Gazette.",
        "The headline is separate from the anonymised notification dataset and must not "
        "be added to its grouped counts.",
        "Source: CNIL, Rapport annuel 2025. Only factual statistics are retained; "
        "the report, article text and images are not reproduced.",
    ]
