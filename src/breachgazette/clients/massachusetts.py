"""Bounded adapter for Massachusetts annual breach-notification reports."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from io import BytesIO

import httpx
import pdfplumber

from breachgazette.clients.base import (
    AdapterResult,
    BoundedSourceClient,
    SourceClientError,
    source_snapshot,
)
from breachgazette.contracts import (
    DateObservation,
    InformationCategory,
    OrganizationRole,
    PopulationObservation,
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
from breachgazette.contracts.models import RecordProvenance
from breachgazette.utils import normalize_organization_name, normalize_text, sha256_hex

REPORTS_URL = "https://www.mass.gov/lists/data-breach-notification-reports"
REPORT_URLS = {
    2024: "https://www.mass.gov/doc/data-breach-report-2024/download",
    2025: "https://www.mass.gov/doc/data-breach-report-2025/download",
    2026: "https://www.mass.gov/doc/data-breach-report-2026/download",
}
REPORT_YEARS = tuple(sorted(REPORT_URLS))
REPORT_RANGE = f"{REPORT_YEARS[0]}-{REPORT_YEARS[-1]}"
EXPECTED_HEADERS = (
    "Breach Number",
    "Date Reported To OCA",
    "Reporting Organization Name",
    "Reporting Organization Type",
    "MA Residents Affected",
    "SSN Breached",
    "Medical Records Breached",
    "Financial Account Breached",
    "Drivers Licenses Breached",
    "Credit/Debit Numbers Breached",
)
INFORMATION_COLUMNS = {
    "SSN Breached": "social_security_number",
    "Medical Records Breached": "medical_records",
    "Financial Account Breached": "financial_account",
    "Drivers Licenses Breached": "drivers_license",
    "Credit/Debit Numbers Breached": "credit_debit_card",
}
EXTRACTION_REPAIRS = {
    "B a n k s & C r e d i t U n i o n s": "Banks & Credit Unions",
}


def _clean_cell(value: object) -> str:
    return normalize_text(str(value or "").replace("\n", " "), maximum=1_000)


def _extract_rows(pdf_bytes: bytes) -> list[dict[str, str]]:
    if not pdf_bytes.startswith(b"%PDF"):
        raise SourceClientError("Massachusetts report was not a PDF")
    rows: list[dict[str, str]] = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as report:
            if not report.pages or len(report.pages) > 1_000:
                raise SourceClientError("Massachusetts report page count exceeded its bound")
            for page in report.pages:
                table = page.extract_table()
                if not table:
                    raise SourceClientError("Massachusetts report table could not be extracted")
                headers = tuple(_clean_cell(value) for value in table[0])
                if headers != EXPECTED_HEADERS:
                    raise SourceClientError("Massachusetts report schema changed")
                for raw_row in table[1:]:
                    if len(raw_row) != len(EXPECTED_HEADERS):
                        raise SourceClientError("Massachusetts report row width changed")
                    row = {
                        header: _clean_cell(value)
                        for header, value in zip(EXPECTED_HEADERS, raw_row, strict=True)
                    }
                    if any(row.values()):
                        rows.append(row)
    except SourceClientError:
        raise
    except Exception as exc:
        raise SourceClientError("Massachusetts PDF parsing failed safely") from exc
    return rows


def _excluded_row_reason(row: dict[str, str]) -> str | None:
    if (
        row["Date Reported To OCA"] == "-"
        and row["Reporting Organization Name"] == "-"
        and all(
            value in {"-", "0"}
            for header, value in row.items()
            if header != "Breach Number"
        )
    ):
        return "placeholder"
    if re.fullmatch(
        r"DUPLICATE OF \d{4}-\d+",
        row["Reporting Organization Name"],
    ) and all(
        not row[header]
        for header in EXPECTED_HEADERS[3:]
    ):
        return "duplicate_marker"
    return None


def _parse_rows(
    rows_by_year: dict[int, list[dict[str, str]]],
    *,
    checksum: str,
    observed_at: datetime,
) -> list[RecordProvenance]:
    revision = f"annual-reports-{REPORT_RANGE}:{checksum[:16]}"
    records: list[RecordProvenance] = []
    seen_ids: set[str] = set()
    for year, rows in sorted(rows_by_year.items()):
        for row in rows:
            if _excluded_row_reason(row):
                continue
            breach_number = "".join(row["Breach Number"].split())
            if not breach_number.startswith(f"{year}-") or breach_number in seen_ids:
                raise SourceClientError("Massachusetts breach number was invalid or duplicated")
            seen_ids.add(breach_number)
            try:
                reported_date = datetime.strptime(
                    row["Date Reported To OCA"], "%d-%b-%y"
                ).date()
            except ValueError as exc:
                raise SourceClientError("Massachusetts date format changed") from exc
            affected_raw = row["MA Residents Affected"]
            try:
                affected = (
                    int(affected_raw.replace(",", ""))
                    if affected_raw
                    else None
                )
            except ValueError as exc:
                raise SourceClientError("Massachusetts population format changed") from exc
            organization = row["Reporting Organization Name"]
            if not organization:
                raise SourceClientError("Massachusetts record omitted reporting organization")
            categories: list[InformationCategory] = []
            information_flags = [row[column] for column in INFORMATION_COLUMNS]
            if any(not value for value in information_flags) and any(
                information_flags
            ):
                raise SourceClientError(
                    "Massachusetts information flags were only partially populated"
                )
            for column, normalized in INFORMATION_COLUMNS.items():
                source_value = row[column]
                compact_value = source_value.replace(" ", "")
                if compact_value not in {"", "Yes", "No"}:
                    raise SourceClientError("Massachusetts information flag changed")
                if compact_value == "Yes":
                    categories.append(
                        InformationCategory(
                            source_label=column.removesuffix(" Breached"),
                            normalized_label=normalized,
                            origin=ValueOrigin.SOURCE_OBSERVED,
                        )
                    )
            limitations = [
                "The reporting organization may differ from every affected entity.",
                f"Coverage is bounded to the reviewed {REPORT_YEARS[0]} through "
                f"{REPORT_YEARS[-1]} annual reports.",
                "Consumer notification letters are not retrieved or reproduced.",
            ]
            if affected is None:
                limitations.append(
                    "The source row omitted the Massachusetts-resident count."
                )
            if not any(information_flags):
                limitations.append(
                    "The source row omitted all reviewed information-category flags."
                )
            affected_state = ValueState.PRESENT
            if affected is None:
                affected_state = ValueState.SOURCE_OMITTED
            elif affected == 0:
                affected_state = ValueState.ZERO
            records.append(
                SourceNotificationRecord(
                    source_id="massachusetts",
                    source_record_id=f"ma:{breach_number}",
                    source_url=REPORTS_URL,
                    source_detail_url=REPORT_URLS[year],
                    source_revision=revision,
                    source_checksum=checksum,
                    source_completeness=Completeness.COMPLETE,
                    source_retrieval_time=observed_at,
                    local_first_observed_time=observed_at,
                    local_last_observed_time=observed_at,
                    parser_version="1.0",
                    normalization_version="1.0",
                    limitations=limitations,
                    regulator="Massachusetts Office of Consumer Affairs and Business Regulation",
                    jurisdiction="Massachusetts",
                    reporting_scheme="Massachusetts data breach notification reporting",
                    publication_level=PublicationLevel.NAMED_NOTIFICATION,
                    coverage_type=CoverageType.BOUNDED_HISTORICAL_DATASET,
                    named_entity=OrganizationRole(
                        source_name=organization,
                        normalized_name=normalize_organization_name(organization),
                        role=EntityRole.NOTIFYING_ENTITY,
                        origin=ValueOrigin.SOURCE_OBSERVED,
                    ),
                    dates=[
                        DateObservation(
                            meaning="regulator_submission_date",
                            raw_value=row["Date Reported To OCA"],
                            normalized_date=reported_date,
                            origin=ValueOrigin.SOURCE_OBSERVED,
                            state=ValueState.PRESENT,
                        )
                    ],
                    affected_population=PopulationObservation(
                        count=affected,
                        scope="Massachusetts residents",
                        estimated=False,
                        origin=ValueOrigin.SOURCE_OBSERVED,
                        state=affected_state,
                    ),
                    information_categories=categories,
                    industry=(
                        EXTRACTION_REPAIRS.get(
                            row["Reporting Organization Type"],
                            row["Reporting Organization Type"],
                        )
                        or None
                    ),
                    register_window_state="not_applicable",
                )
            )
    return records


class MassachusettsAdapter:
    source_id = "massachusetts"
    adapter_version = "1.0"
    normalization_version = "1.0"
    max_rows = 10_000

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def collect(self, *, observed_at: datetime | None = None) -> AdapterResult:
        observed_at = observed_at or datetime.now(UTC)
        reports: dict[int, bytes] = {}
        with BoundedSourceClient(
            allowed_origins={"https://www.mass.gov"},
            allowed_path_prefixes=("/doc/data-breach-report-",),
            max_response_bytes=5_000_000,
            total_deadline_seconds=180,
            transport=self.transport,
            user_agent=(
                "Mozilla/5.0 (compatible; BreachGazette/0.1; "
                "+https://github.com/slicedearth)"
            ),
        ) as client:
            for year, url in sorted(REPORT_URLS.items()):
                content, headers, _final_url = client.get_bytes(url, accept="application/pdf")
                if "pdf" not in headers.get("Content-Type", "").casefold():
                    raise SourceClientError(
                        "Massachusetts report returned an unexpected content type"
                    )
                reports[year] = content
        rows_by_year = {year: _extract_rows(content) for year, content in reports.items()}
        exclusion_counts = {
            reason: sum(
                _excluded_row_reason(row) == reason
                for rows in rows_by_year.values()
                for row in rows
            )
            for reason in ("placeholder", "duplicate_marker")
        }
        excluded_rows = sum(exclusion_counts.values())
        discovered = sum(len(rows) for rows in rows_by_year.values()) - excluded_rows
        if discovered <= 0 or discovered > self.max_rows:
            raise SourceClientError("Massachusetts row count was empty or exceeded its bound")
        checksum = sha256_hex(
            [[year, sha256_hex(content)] for year, content in sorted(reports.items())]
        )
        records = _parse_rows(
            rows_by_year,
            checksum=checksum,
            observed_at=observed_at,
        )
        snapshot = source_snapshot(
            source_id=self.source_id,
            retrieved_at=observed_at,
            revision=f"annual-reports-{REPORT_RANGE}:{checksum[:16]}",
            checksum=checksum,
            completeness=Completeness.COMPLETE,
            discovered=discovered,
            accepted=len(records),
            rejected=0,
            bounded_limit=self.max_rows,
            notes=[
                f"Parsed the official {REPORT_YEARS[0]} through "
                f"{REPORT_YEARS[-1]} annual report tables.",
                "Consumer notification letters were not retrieved.",
                (
                    f"Excluded {exclusion_counts['placeholder']} source placeholder rows and "
                    f"{exclusion_counts['duplicate_marker']} duplicate-marker rows containing "
                    "no independent notification facts."
                ),
            ],
        )
        return AdapterResult(
            source_id=self.source_id,
            records=records,
            snapshot=snapshot,
        )
