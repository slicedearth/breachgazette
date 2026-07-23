"""Adapter for the California Attorney General's official full CSV export."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import UTC, datetime
from io import StringIO

import httpx

from breachgazette.clients.base import (
    AdapterResult,
    BoundedSourceClient,
    SourceClientError,
    source_snapshot,
)
from breachgazette.contracts import DateObservation, OrganizationRole, SourceNotificationRecord
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

CSV_URL = "https://oag.ca.gov/privacy/databreach/list-export"
LIST_URL = "https://oag.ca.gov/privacy/databreach/list"
HEADERS = (
    "Organization Name",
    "Date(s) of Breach  (if known)",
    "Reported Date",
)


def _date_observations(raw: str, reported: str) -> list[DateObservation]:
    observations: list[DateObservation] = []
    if raw.casefold() == "n/a" or not raw:
        observations.append(
            DateObservation(
                meaning="occurrence_start",
                raw_value=raw or None,
                normalized_date=None,
                origin=ValueOrigin.SOURCE_OBSERVED,
                state=ValueState.SOURCE_OMITTED,
            )
        )
    else:
        for component in (part.strip() for part in raw.split(",")):
            normalized = None
            try:
                normalized = datetime.strptime(component, "%m/%d/%Y").date()
            except ValueError as exc:
                raise SourceClientError("California breach date format changed") from exc
            observations.append(
                DateObservation(
                    meaning="occurrence_start",
                    raw_value=component,
                    normalized_date=normalized,
                    origin=ValueOrigin.SOURCE_OBSERVED,
                    state=ValueState.PRESENT,
                )
            )
    try:
        reported_date = datetime.strptime(reported, "%m/%d/%Y").date()
    except ValueError as exc:
        raise SourceClientError("California reported date format changed") from exc
    observations.append(
        DateObservation(
            meaning="regulator_submission_date",
            raw_value=reported,
            normalized_date=reported_date,
            origin=ValueOrigin.SOURCE_OBSERVED,
            state=ValueState.PRESENT,
        )
    )
    return observations


class CaliforniaAdapter:
    source_id = "california"
    adapter_version = "1.0"
    normalization_version = "1.0"
    max_rows = 20_000

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def collect(self, *, observed_at: datetime | None = None) -> AdapterResult:
        observed_at = observed_at or datetime.now(UTC)
        with BoundedSourceClient(
            allowed_origins={"https://oag.ca.gov", "https://www.oag.ca.gov"},
            allowed_path_prefixes=("/privacy/databreach/list-export",),
            max_response_bytes=12_000_000,
            transport=self.transport,
        ) as client:
            csv_bytes, headers, _url = client.get_bytes(CSV_URL, accept="text/csv")
            content_type = headers.get("Content-Type", "").lower()
            if "csv" not in content_type and "text/plain" not in content_type:
                raise SourceClientError("California export returned an unexpected content type")
        try:
            text = csv_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SourceClientError("California CSV was not UTF-8") from exc
        reader = csv.DictReader(StringIO(text))
        if tuple(reader.fieldnames or ()) != HEADERS:
            raise SourceClientError("California CSV schema changed")
        raw_rows = list(reader)
        if not raw_rows or len(raw_rows) > self.max_rows:
            raise SourceClientError("California row count was empty or exceeded its bound")
        checksum = sha256_hex(csv_bytes)
        duplicate_ordinals: dict[str, int] = defaultdict(int)
        records: list[RecordProvenance] = []
        for row in raw_rows:
            name = normalize_text(row[HEADERS[0]], maximum=500)
            breach_dates = normalize_text(row[HEADERS[1]], maximum=500)
            reported_date = normalize_text(row[HEADERS[2]], maximum=100)
            row_hash = sha256_hex([name, breach_dates, reported_date])
            duplicate_ordinals[row_hash] += 1
            ordinal = duplicate_ordinals[row_hash]
            record_id = f"ca:{row_hash[:24]}:{ordinal}"
            source_name = name or "Organization name not published"
            normalized_name = (
                normalize_organization_name(name)
                if name
                else f"organization-name-not-published-{row_hash[:12]}"
            )
            records.append(
                SourceNotificationRecord(
                    source_id=self.source_id,
                    source_record_id=record_id,
                    source_url=LIST_URL,
                    source_revision=checksum[:16],
                    source_checksum=checksum,
                    source_completeness=Completeness.COMPLETE,
                    source_retrieval_time=observed_at,
                    local_first_observed_time=observed_at,
                    local_last_observed_time=observed_at,
                    parser_version=self.adapter_version,
                    normalization_version=self.normalization_version,
                    limitations=[
                        "The source-labelled notifier may not be the entity where the "
                        "event occurred.",
                        "The CSV does not provide a stable source ID or detail URL.",
                    ],
                    regulator="California Department of Justice, Office of the Attorney General",
                    jurisdiction="California",
                    reporting_scheme="California Civil Code sections 1798.29 and 1798.82",
                    publication_level=PublicationLevel.NAMED_NOTIFICATION,
                    coverage_type=CoverageType.COMPLETE_PUBLISHED_DATASET,
                    named_entity=OrganizationRole(
                        source_name=source_name,
                        normalized_name=normalized_name,
                        role=EntityRole.NOTIFYING_ENTITY if name else EntityRole.UNKNOWN,
                        origin=ValueOrigin.SOURCE_OBSERVED if name else ValueOrigin.NORMALIZED,
                        state=ValueState.PRESENT if name else ValueState.SOURCE_OMITTED,
                    ),
                    dates=_date_observations(breach_dates, reported_date),
                    register_window_state="not_applicable",
                )
            )
        snapshot = source_snapshot(
            source_id=self.source_id,
            retrieved_at=observed_at,
            revision=checksum[:16],
            checksum=checksum,
            completeness=Completeness.COMPLETE,
            discovered=len(raw_rows),
            accepted=len(records),
            rejected=0,
            bounded_limit=self.max_rows,
            notes=[
                "No sample notification letters were retrieved.",
                "Stable record IDs are deterministic hashes of the three official CSV fields.",
            ],
        )
        return AdapterResult(source_id=self.source_id, records=records, snapshot=snapshot)
