"""Narrow adapters for the NSW public register and the reviewed PDF sector table."""

from __future__ import annotations

import re
from contextlib import suppress
from datetime import UTC, date, datetime
from io import BytesIO
from urllib.parse import urljoin

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from breachgazette.clients.base import (
    AdapterResult,
    BoundedSourceClient,
    SourceClientError,
    source_snapshot,
)
from breachgazette.contracts import (
    DateObservation,
    OrganizationRole,
    SourceAggregateRecord,
    SourceNotificationRecord,
)
from breachgazette.contracts.enums import (
    Completeness,
    CoverageType,
    EntityRole,
    PublicationLevel,
    ValueOrigin,
    ValueState,
)
from breachgazette.contracts.models import ObservedValue, RecordProvenance
from breachgazette.utils import (
    normalize_organization_name,
    normalize_text,
    sanitize_public_url,
    sha256_hex,
)

REGISTER_URL = "https://www.ipc.nsw.gov.au/privacy/MNDB-scheme/public-notifications"
REPORTING_URL = "https://www.ipc.nsw.gov.au/Reporting-on-the-Scheme"
EXPECTED_TABLE_METRICS = (
    "Number of notifications",
    "Percent caused by human error",
    "Percent caused by criminal or malicious attack",
    "Percent with multiple causes",
    "Number of affected individuals",
)
EXPECTED_SECTORS = (
    "Government",
    "Local Government",
    "University",
    "State Owned Corporation",
    "Total",
)


def _date_observation(meaning: str, raw: str, observed_at: datetime) -> DateObservation:
    normalized: date | None = None
    with suppress(ValueError):
        normalized = datetime.strptime(raw, "%d %B %Y").date()
    return DateObservation(
        meaning=meaning,
        raw_value=raw,
        normalized_date=normalized,
        origin=ValueOrigin.SOURCE_OBSERVED,
        state=ValueState.PRESENT,
    )


class NswPublicNotificationsAdapter:
    source_id = "nsw_public_notifications"
    adapter_version = "1.0"
    normalization_version = "1.0"
    max_records = 500

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def collect(self, *, observed_at: datetime | None = None) -> AdapterResult:
        observed_at = observed_at or datetime.now(UTC)
        with BoundedSourceClient(
            allowed_origins={"https://www.ipc.nsw.gov.au"},
            allowed_path_prefixes=("/privacy/MNDB-scheme/public-notifications",),
            max_response_bytes=3_000_000,
            transport=self.transport,
        ) as client:
            html, _headers, _final_url = client.get_text(REGISTER_URL)
        checksum = sha256_hex(html)
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.select("main table, .page-layout__content table")
        if len(tables) < 2:
            raise SourceClientError("NSW register did not expose current and expired tables")
        records: list[RecordProvenance] = []
        for table_index, table in enumerate(tables[:2]):
            headers = [
                normalize_text(header.get_text(" ", strip=True), maximum=200)
                for header in table.select("thead th")
            ]
            expected = ["Agency Public Notification Date", "Agency Date of Incident", "Agency Name"]
            if [header.casefold() for header in headers[:3]] != [
                header.casefold() for header in expected
            ]:
                raise SourceClientError("NSW public register column schema changed")
            state = "current" if table_index == 0 else "expired"
            for row in table.select("tbody tr"):
                cells = row.find_all("td", recursive=False)
                if len(cells) < 3:
                    continue
                publication_date = normalize_text(cells[0].get_text(" ", strip=True), maximum=300)
                incident_date = normalize_text(cells[1].get_text(" ", strip=True), maximum=500)
                agency = normalize_text(cells[2].get_text(" ", strip=True), maximum=500)
                if not agency:
                    continue
                detail_url: str | None = None
                link = cells[3].find("a", href=True) if len(cells) >= 4 else None
                if link is not None:
                    detail_url = sanitize_public_url(str(link["href"]))
                record_id = f"nsw:{sha256_hex([publication_date, incident_date, agency])[:24]}"
                records.append(
                    SourceNotificationRecord(
                        source_id=self.source_id,
                        source_record_id=record_id,
                        source_url=REGISTER_URL,
                        source_revision=checksum[:16],
                        source_checksum=checksum,
                        source_completeness=Completeness.ROLLING_WINDOW,
                        source_retrieval_time=observed_at,
                        local_first_observed_time=observed_at,
                        local_last_observed_time=observed_at,
                        parser_version=self.adapter_version,
                        normalization_version=self.normalization_version,
                        limitations=[
                            "This register is not a complete list of all NSW public-sector "
                            "data breaches.",
                            "Register expiry is not evidence of remediation.",
                        ],
                        regulator="Information and Privacy Commission NSW",
                        jurisdiction="New South Wales",
                        reporting_scheme="Mandatory Notification of Data Breach Scheme",
                        publication_level=PublicationLevel.REGULATOR_REGISTER_ENTRY,
                        coverage_type=CoverageType.ROLLING_PUBLIC_WINDOW,
                        named_entity=OrganizationRole(
                            source_name=agency,
                            normalized_name=normalize_organization_name(agency),
                            role=EntityRole.PUBLIC_SECTOR_AGENCY,
                            origin=ValueOrigin.SOURCE_OBSERVED,
                        ),
                        dates=[
                            _date_observation(
                                "public_notification_date", publication_date, observed_at
                            ),
                            _date_observation("occurrence_start", incident_date, observed_at),
                        ],
                        register_window_state=state,
                        source_detail_url=detail_url,
                    )
                )
        if not records or len(records) > self.max_records:
            raise SourceClientError("NSW register was empty or exceeded its bound")
        snapshot = source_snapshot(
            source_id=self.source_id,
            retrieved_at=observed_at,
            revision=checksum[:16],
            checksum=checksum,
            completeness=Completeness.ROLLING_WINDOW,
            discovered=len(records),
            accepted=len(records),
            rejected=0,
            bounded_limit=self.max_records,
            notes=[
                "Current links are published for at least 12 months.",
                "Expired records remain source-window records, not deleted incidents.",
            ],
        )
        return AdapterResult(source_id=self.source_id, records=records, snapshot=snapshot)


def _parse_period(text: str) -> tuple[date, date]:
    match = re.search(
        r"(January|Jan|July|Jul)\s*(?:to|\u2013|-)\s*(June|Jun|December|Dec)\s+(\d{4})",
        text,
    )
    if not match:
        raise SourceClientError("NSW snapshot title omitted its six-month period")
    year = int(match.group(3))
    if match.group(1) in {"July", "Jul"}:
        return date(year, 7, 1), date(year, 12, 31)
    return date(year, 1, 1), date(year, 6, 30)


def _cell_value(text: str) -> tuple[int | None, str, ValueState]:
    normalized = text.strip().replace(",", "")
    normalized = re.sub(r"(?<=%)\d+$", "", normalized)
    if normalized.upper() == "N/A":
        return None, "count", ValueState.NOT_APPLICABLE
    if normalized.endswith("%"):
        return int(normalized[:-1]), "percent", ValueState.ESTIMATED
    return int(normalized), "count", ValueState.PRESENT


class NswAggregateAdapter:
    source_id = "nsw_mndb_aggregate"
    adapter_version = "1.0"
    normalization_version = "1.0"
    max_records = 25

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def collect(self, *, observed_at: datetime | None = None) -> AdapterResult:
        observed_at = observed_at or datetime.now(UTC)
        with BoundedSourceClient(
            allowed_origins={"https://www.ipc.nsw.gov.au"},
            allowed_path_prefixes=(
                "/Reporting-on-the-Scheme",
                "/node/",
                "/resources/mndb-scheme-data-snapshot-",
                "/media/",
                "/sites/default/files/",
            ),
            max_response_bytes=8_000_000,
            transport=self.transport,
        ) as client:
            index_html, _headers, _url = client.get_text(REPORTING_URL)
            index = BeautifulSoup(index_html, "html.parser")
            links = [
                link
                for link in index.find_all("a", href=True)
                if "MNDB Scheme Data Snapshot" in link.get_text(" ", strip=True)
            ]
            if not links:
                raise SourceClientError("NSW reporting index omitted snapshot links")
            snapshot_link = links[0]
            snapshot_title = normalize_text(snapshot_link.get_text(" ", strip=True), maximum=300)
            snapshot_url = urljoin(REPORTING_URL, str(snapshot_link["href"]))
            page_html, _headers, _url = client.get_text(snapshot_url)
            snapshot_page = BeautifulSoup(page_html, "html.parser")
            media_hrefs = sorted(
                {
                    str(link["href"])
                    for link in snapshot_page.find_all("a", href=True)
                    if "MNDB Scheme Data Snapshot" in link.get_text(" ", strip=True)
                    and str(link["href"]).startswith("/media/")
                }
            )
            if len(media_hrefs) != 1:
                raise SourceClientError("NSW snapshot page did not expose one reviewed PDF")
            pdf_url = urljoin(snapshot_url, media_hrefs[0])
            pdf_bytes, pdf_headers, final_pdf_url = client.get_bytes(
                pdf_url,
                accept="application/pdf",
            )
            if "pdf" not in pdf_headers.get(
                "Content-Type", ""
            ).lower() and not pdf_bytes.startswith(b"%PDF-"):
                raise SourceClientError("NSW media resource was not a PDF")

        period_start, period_end = _parse_period(snapshot_title)
        checksum = sha256_hex(pdf_bytes)
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            if len(pdf.pages) != 8:
                raise SourceClientError("NSW snapshot page count changed")
            pdf_page = pdf.pages[4]
            page_text = pdf_page.extract_text() or ""
            normalized_page_text = normalize_text(page_text, maximum=20_000)
            for marker in (
                "Sector Snapshot",
                "during the reporting period",
            ):
                if marker not in normalized_page_text:
                    raise SourceClientError("NSW reviewed table marker changed")
            extracted_tables = pdf_page.extract_tables()
            if not extracted_tables:
                raise SourceClientError("NSW reviewed sector table was not detected")
            table = extracted_tables[0]
        header = [normalize_text(str(cell or ""), maximum=100) for cell in table[0][3:8]]
        if tuple(header) != EXPECTED_SECTORS:
            raise SourceClientError("NSW sector table headers changed")
        numeric_rows: list[list[str]] = []
        for row in table[1:]:
            values = [normalize_text(str(cell or ""), maximum=100) for cell in row[3:8]]
            if (
                any(re.fullmatch(r"(?:N/A|[\d,]+%?\d*)", value) for value in values)
                and len(values) == 5
                and all(values)
            ):
                numeric_rows.append(values)
        if len(numeric_rows) != len(EXPECTED_TABLE_METRICS):
            raise SourceClientError("NSW sector table row layout changed")

        records: list[RecordProvenance] = []
        for metric, values in zip(EXPECTED_TABLE_METRICS, numeric_rows, strict=True):
            for sector, raw_value in zip(EXPECTED_SECTORS, values, strict=True):
                value, unit, state = _cell_value(raw_value)
                record_id = f"nsw-sector:{sha256_hex([period_start, metric, sector])[:20]}"
                records.append(
                    SourceAggregateRecord(
                        source_id=self.source_id,
                        source_record_id=record_id,
                        source_url=final_pdf_url,
                        source_revision=checksum[:16],
                        source_checksum=checksum,
                        source_completeness=Completeness.COMPLETE,
                        source_retrieval_time=observed_at,
                        local_first_observed_time=observed_at,
                        local_last_observed_time=observed_at,
                        parser_version=self.adapter_version,
                        normalization_version=self.normalization_version,
                        limitations=[
                            "Extracted only from the page 5 sector table.",
                            "Chart-only values are intentionally excluded.",
                        ],
                        regulator="Information and Privacy Commission NSW",
                        reporting_scheme="Mandatory Notification of Data Breach Scheme",
                        publication_level=PublicationLevel.STATE_AGGREGATE,
                        reporting_period_start=period_start,
                        reporting_period_end=period_end,
                        dimension="sector_snapshot",
                        category=metric,
                        parent_category=sector,
                        value=ObservedValue(
                            value=value,
                            origin=ValueOrigin.SOURCE_OBSERVED,
                            state=state,
                            source_label=raw_value,
                        ),
                        unit=unit,
                        population_scope="NSW public sector MNDB notifications",
                        rounding_state=state,
                        source_notes=[
                            "Percentages may not total 100 percent due to rounding.",
                            "Agencies may select more than one cause.",
                        ],
                    )
                )
        snapshot = source_snapshot(
            source_id=self.source_id,
            retrieved_at=observed_at,
            revision=checksum[:16],
            checksum=checksum,
            completeness=Completeness.COMPLETE,
            discovered=len(records),
            accepted=len(records),
            rejected=0,
            bounded_limit=self.max_records,
            notes=[
                "Layout-aware extraction is restricted to page 5 and the sector table.",
                "Raster chart values are not inferred.",
            ],
        )
        return AdapterResult(source_id=self.source_id, records=records, snapshot=snapshot)
