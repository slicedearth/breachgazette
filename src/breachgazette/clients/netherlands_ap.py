"""Bounded adapter for Netherlands AP annual data-breach aggregates."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from html.parser import HTMLParser

import httpx

from breachgazette.clients.base import (
    AdapterResult,
    BoundedSourceClient,
    SourceClientError,
    source_snapshot,
)
from breachgazette.contracts import SourceAggregateRecord
from breachgazette.contracts.enums import (
    Completeness,
    PublicationLevel,
    ValueOrigin,
    ValueState,
)
from breachgazette.contracts.models import ObservedValue, RecordProvenance
from breachgazette.utils import normalize_text, sha256_hex

REPORT_URL = (
    "https://autoriteitpersoonsgegevens.nl/actueel/"
    "ai-vergroot-gevaren-van-cyberaanvallen"
)
SOURCE_UPDATED_AT = datetime(2026, 7, 8, tzinfo=UTC)
TITLE_MARKER = "vergroot gevaren van cyberaanvallen"
TOTAL_PATTERN = re.compile(
    r"In totaal zijn in 2025 bij de AP (?P<total_2025>\d{1,3}(?:\.\d{3})*) "
    r"datalekken gemeld, tegenover (?P<total_2024>\d{1,3}(?:\.\d{3})*) in 2024\. "
    r"Cyberaanvallen waren de oorzaak van "
    r"(?P<cyberattacks_2025>\d{1,3}(?:\.\d{3})*) van de gemelde datalekken\."
)
ACCOUNT_PATTERN = re.compile(
    r"van (?P<account_takeovers_2024>\d{1,3}(?:\.\d{3})*) in 2024 "
    r"naar (?P<account_takeovers_2025>\d{1,3}(?:\.\d{3})*) in 2025"
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        _attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template"}:
            self.hidden_depth = max(0, self.hidden_depth - 1)

    def handle_data(self, data: str) -> None:
        if self.hidden_depth == 0:
            self.parts.append(data)


def _visible_text(content: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(content)
    parser.close()
    return normalize_text(" ".join(parser.parts), maximum=200_000)


def _integer(value: str) -> int:
    return int(value.replace(".", ""))


class NetherlandsApAdapter:
    source_id = "netherlands_ap"
    adapter_version = "1.0"
    normalization_version = "1.0"
    max_records = 10

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def collect(self, *, observed_at: datetime | None = None) -> AdapterResult:
        observed_at = observed_at or datetime.now(UTC)
        with BoundedSourceClient(
            allowed_origins={
                "https://autoriteitpersoonsgegevens.nl",
                "https://www.autoriteitpersoonsgegevens.nl",
            },
            allowed_path_prefixes=(
                "/actueel/ai-vergroot-gevaren-van-cyberaanvallen",
            ),
            max_response_bytes=1_000_000,
            transport=self.transport,
        ) as client:
            content, _headers, _final_url = client.get_text(REPORT_URL)

        text = _visible_text(content)
        if TITLE_MARKER not in text:
            raise SourceClientError("Netherlands AP report title changed")
        totals = TOTAL_PATTERN.search(text)
        account_takeovers = ACCOUNT_PATTERN.search(text)
        if totals is None or account_takeovers is None:
            raise SourceClientError("Netherlands AP annual aggregate markers changed")

        values = {
            **{key: _integer(value) for key, value in totals.groupdict().items()},
            **{
                key: _integer(value)
                for key, value in account_takeovers.groupdict().items()
            },
        }
        checksum = sha256_hex(content.encode("utf-8"))
        revision = f"ap-datalekken-2025:{checksum[:16]}"
        specifications = (
            (
                "breach_notifications_received",
                "All data breach notifications received",
                2025,
                values["total_2025"],
            ),
            (
                "breach_notifications_received",
                "All data breach notifications received",
                2024,
                values["total_2024"],
            ),
            (
                "reported_cause",
                "Cyberattack",
                2025,
                values["cyberattacks_2025"],
            ),
            (
                "incident_type",
                "Account takeover",
                2025,
                values["account_takeovers_2025"],
            ),
            (
                "incident_type",
                "Account takeover",
                2024,
                values["account_takeovers_2024"],
            ),
        )
        notes = [
            "Counts are source-reported notifications, not independently verified incidents.",
            "Cause and incident-type dimensions can overlap and must not be summed.",
            "Only attributed factual aggregates are retained; source prose is not redistributed.",
        ]
        records: list[RecordProvenance] = [
            SourceAggregateRecord(
                source_id=self.source_id,
                source_record_id=f"nl:ap:{dimension}:{year}",
                source_url=REPORT_URL,
                source_revision=revision,
                source_checksum=checksum,
                source_completeness=Completeness.COMPLETE,
                source_retrieval_time=observed_at,
                local_first_observed_time=observed_at,
                local_last_observed_time=observed_at,
                parser_version=self.adapter_version,
                normalization_version=self.normalization_version,
                limitations=[
                    "Annual aggregate dimensions are not directly additive.",
                    "The source may revise its published figures.",
                ],
                regulator="Autoriteit Persoonsgegevens",
                reporting_scheme="GDPR personal data breach notifications",
                publication_level=PublicationLevel.NATIONAL_AGGREGATE,
                reporting_period_start=date(year, 1, 1),
                reporting_period_end=date(year, 12, 31),
                dimension=dimension,
                category=category,
                value=ObservedValue(
                    value=value,
                    origin=ValueOrigin.SOURCE_OBSERVED,
                    state=ValueState.PRESENT,
                    source_label=f"{value:,}".replace(",", "."),
                ),
                unit="notifications",
                population_scope="Notifications received by Autoriteit Persoonsgegevens",
                source_notes=notes,
            )
            for dimension, category, year, value in specifications
        ]
        if len(records) != 5 or len(records) > self.max_records:
            raise SourceClientError("Netherlands AP metric count failed its bound")

        snapshot = source_snapshot(
            source_id=self.source_id,
            retrieved_at=observed_at,
            revision=revision,
            checksum=checksum,
            completeness=Completeness.COMPLETE,
            discovered=len(records),
            accepted=len(records),
            rejected=0,
            bounded_limit=self.max_records,
            source_updated_at=SOURCE_UPDATED_AT,
            notes=notes,
        )
        return AdapterResult(
            source_id=self.source_id,
            records=records,
            snapshot=snapshot,
        )
