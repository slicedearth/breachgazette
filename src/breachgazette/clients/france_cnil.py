"""Bounded adapter for the CNIL anonymized breach-notification dataset."""

from __future__ import annotations

import calendar
import csv
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from io import StringIO
from typing import Any

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

DATASET_ID = "5cd42a86634f4147a23df1be"
DATASET_URL = (
    "https://www.data.gouv.fr/datasets/"
    "notifications-a-la-cnil-de-violations-de-donnees-a-caractere-personnel"
)
DATASET_API_URL = f"https://www.data.gouv.fr/api/1/datasets/{DATASET_ID}/"
RESOURCE_PATH_PREFIX = (
    "/resources/notifications-a-la-cnil-de-violations-de-donnees-"
    "a-caractere-personnel/"
)
EXPECTED_DATASET_TITLE = (
    "Notifications à la CNIL de violations de données à caractère personnel"
)
EXPECTED_HEADERS = (
    "Date de réception de la notification",
    "Secteur d'activité de l'organisme concerné",
    "Natures de la violation",
    "Nombre de personnes impactées",
    "Typologies des données impactées",
    "Données sensibles",
    "Origines de l'incident",
    "Causes de l'incident",
    "Information des personnes",
)
BREACH_NATURES = {
    "Perte de la confidentialité",
    "Perte de l'intégrité",
    "Perte de la disponibilité",
}
INCIDENT_CAUSES = {
    "Acte externe accidentel",
    "Acte externe malveillant",
    "Acte interne accidentel",
    "Acte interne malveillant",
    "Autre",
    "Inconnu",
}
POPULATION_BANDS = {
    "Entre 0 et 5 personnes",
    "Entre 6 et 50 personnes",
    "Entre 51 et 300 personnes",
    "Entre 301 et 5000 personnes",
    "Plus de 5000 personnes",
}
INFORMATION_STATES = {
    "Non, mais elles le seront",
    "Non déterminé pour le moment",
    "Oui, les personnes ont été informées",
    "Non ils ne le seront pas",
}
RESOURCE_TITLE = re.compile(r"^opencnil-violationsdcpnotifiees-(\d{8})\.csv$")
EARLIEST_MONTH = date(2018, 5, 1)


@dataclass(frozen=True, slots=True)
class CnilRow:
    received_month: date
    sector: str
    breach_natures: tuple[str, ...]
    population_band: str
    sensitive_data: str
    incident_causes: tuple[str, ...]
    individuals_informed: str


@dataclass(frozen=True, slots=True)
class CnilResource:
    resource_id: str
    title: str
    url: str
    last_modified: datetime
    coverage_end: date


def _parse_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise SourceClientError(f"CNIL {field} timestamp was missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceClientError(f"CNIL {field} timestamp changed") from exc
    if parsed.tzinfo is None:
        raise SourceClientError(f"CNIL {field} timestamp omitted its timezone")
    return parsed.astimezone(UTC)


def _select_csv_resource(payload: Any) -> CnilResource:
    if not isinstance(payload, dict):
        raise SourceClientError("CNIL dataset metadata was not an object")
    organization = payload.get("organization")
    if (
        payload.get("id") != DATASET_ID
        or payload.get("title") != EXPECTED_DATASET_TITLE
        or payload.get("license") != "lov2"
        or payload.get("private") is not False
        or payload.get("frequency") != "quarterly"
        or not isinstance(organization, dict)
        or organization.get("name") != "CNIL"
    ):
        raise SourceClientError("CNIL dataset identity or licence contract changed")
    resources = payload.get("resources")
    if not isinstance(resources, list):
        raise SourceClientError("CNIL dataset resources were missing")
    csv_resources = [
        resource
        for resource in resources
        if isinstance(resource, dict)
        and str(resource.get("format", "")).casefold() == "csv"
    ]
    if len(csv_resources) != 1:
        raise SourceClientError("CNIL dataset did not expose exactly one CSV resource")
    resource = csv_resources[0]
    resource_id = resource.get("id")
    title = resource.get("title")
    url = resource.get("url")
    filesize = resource.get("filesize")
    if (
        not isinstance(resource_id, str)
        or not isinstance(title, str)
        or not isinstance(url, str)
        or not isinstance(filesize, int)
        or isinstance(filesize, bool)
        or filesize <= 0
        or filesize > CnilAdapter.max_response_bytes
    ):
        raise SourceClientError("CNIL CSV resource metadata exceeded its contract")
    title_match = RESOURCE_TITLE.fullmatch(title)
    if title_match is None or not url.endswith(f"/{title}"):
        raise SourceClientError("CNIL CSV resource title or URL changed")
    try:
        coverage_end = datetime.strptime(title_match.group(1), "%Y%m%d").date()
    except ValueError as exc:
        raise SourceClientError("CNIL CSV coverage date changed") from exc
    dataset_updated = _parse_timestamp(
        payload.get("last_update"),
        field="dataset update",
    )
    resource_updated = _parse_timestamp(
        resource.get("last_modified"),
        field="resource update",
    )
    if dataset_updated < resource_updated:
        raise SourceClientError("CNIL dataset update pre-dated its CSV resource")
    if coverage_end != _month_end(coverage_end):
        raise SourceClientError("CNIL CSV coverage date was not a month boundary")
    return CnilResource(
        resource_id=resource_id,
        title=title,
        url=url,
        last_modified=resource_updated,
        coverage_end=coverage_end,
    )


def _split_fixed_vocabulary(
    value: str,
    *,
    vocabulary: set[str],
    field: str,
) -> tuple[str, ...]:
    items = tuple(part.strip() for part in value.split(","))
    if not items or any(not item or item not in vocabulary for item in items):
        raise SourceClientError(f"CNIL {field} vocabulary changed")
    if len(set(items)) != len(items):
        raise SourceClientError(f"CNIL {field} repeated a category")
    return items


def _parse_csv(
    content: bytes,
    *,
    coverage_end: date,
    earliest_month: date = EARLIEST_MONTH,
) -> list[CnilRow]:
    try:
        text = content.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise SourceClientError("CNIL CSV encoding changed") from exc
    if "\ufffd" in text:
        raise SourceClientError("CNIL CSV contained replacement characters")
    reader = csv.reader(StringIO(text, newline=""), delimiter=";")
    try:
        extraction_note = next(reader)
        raw_headers = next(reader)
    except StopIteration as exc:
        raise SourceClientError("CNIL CSV omitted its note or header row") from exc
    if (
        len(extraction_note) != len(EXPECTED_HEADERS)
        or not extraction_note[0].startswith("Extraction générée le ")
        or any(extraction_note[1:])
    ):
        raise SourceClientError("CNIL CSV extraction note changed")
    headers = tuple(
        normalize_text(header, maximum=200)
        for header in raw_headers
    )
    if headers != EXPECTED_HEADERS:
        raise SourceClientError("CNIL CSV schema changed")

    parsed: list[CnilRow] = []
    for row_number, raw_row in enumerate(reader, start=3):
        if len(raw_row) != len(EXPECTED_HEADERS):
            raise SourceClientError(f"CNIL CSV row {row_number} width changed")
        values = tuple(normalize_text(value, maximum=700) for value in raw_row)
        (
            received,
            sector,
            natures,
            population_band,
            _information_categories,
            sensitive_data,
            incident_origins,
            causes,
            individuals_informed,
        ) = values
        try:
            received_month = datetime.strptime(received, "%Y-%m").date()
        except ValueError as exc:
            raise SourceClientError("CNIL notification month format changed") from exc
        if received_month > coverage_end.replace(day=1):
            raise SourceClientError("CNIL row post-dated the resource coverage boundary")
        if (
            not sector
            or not incident_origins
            or population_band not in POPULATION_BANDS
            or sensitive_data not in {"", "Oui"}
            or individuals_informed not in INFORMATION_STATES
        ):
            raise SourceClientError("CNIL source vocabulary or required field changed")
        parsed.append(
            CnilRow(
                received_month=received_month,
                sector=sector,
                breach_natures=_split_fixed_vocabulary(
                    natures,
                    vocabulary=BREACH_NATURES,
                    field="breach nature",
                ),
                population_band=population_band,
                sensitive_data=sensitive_data,
                incident_causes=_split_fixed_vocabulary(
                    causes,
                    vocabulary=INCIDENT_CAUSES,
                    field="incident cause",
                ),
                individuals_informed=individuals_informed,
            )
        )
    if not parsed:
        raise SourceClientError("CNIL CSV contained no notification rows")
    observed_months = {row.received_month for row in parsed}
    expected_months: set[date] = set()
    month = earliest_month
    while month <= coverage_end.replace(day=1):
        expected_months.add(month)
        month = (
            date(month.year + 1, 1, 1)
            if month.month == 12
            else date(month.year, month.month + 1, 1)
        )
    if observed_months != expected_months:
        raise SourceClientError("CNIL CSV month coverage changed")
    return parsed


def _month_end(month: date) -> date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def _aggregate_records(
    rows: list[CnilRow],
    *,
    resource: CnilResource,
    checksum: str,
    observed_at: datetime,
) -> list[RecordProvenance]:
    first_month = min(row.received_month for row in rows)
    last_month = max(row.received_month for row in rows)
    revision = (
        f"data-gouv-resource:{resource.resource_id}:"
        f"{resource.last_modified.isoformat()}"
    )
    common_notes = [
        "Counts represent anonymized notification rows, not unique breach incidents.",
        "The source warns that one processor incident can produce many controller notifications.",
        "The source excludes the most recent three months for confidentiality.",
        "Raw row combinations are retained neither in the public site nor in durable state.",
    ]
    records: list[RecordProvenance] = []

    def add_metric(
        *,
        dimension: str,
        category: str,
        value: int,
        unit: str = "notification_rows",
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> None:
        identity = sha256_hex([dimension, category])[:20]
        records.append(
            SourceAggregateRecord(
                source_id="france_cnil",
                source_record_id=f"fr:cnil:{dimension}:{identity}",
                source_url=DATASET_URL,
                source_revision=revision,
                source_checksum=checksum,
                source_completeness=Completeness.COMPLETE,
                source_retrieval_time=observed_at,
                local_first_observed_time=observed_at,
                local_last_observed_time=observed_at,
                parser_version="1.0",
                normalization_version="1.0",
                limitations=common_notes,
                regulator="Commission nationale de l'informatique et des libertés",
                reporting_scheme="GDPR personal data breach notifications to CNIL",
                publication_level=PublicationLevel.ANONYMIZED_NOTIFICATION,
                reporting_period_start=period_start or first_month,
                reporting_period_end=period_end or _month_end(last_month),
                dimension=dimension,
                category=category,
                value=ObservedValue(
                    value=value,
                    origin=ValueOrigin.CALCULATED,
                    state=ValueState.PRESENT,
                ),
                unit=unit,
                population_scope=(
                    "Notification rows in the published CNIL anonymized dataset"
                ),
                rounding_state=ValueState.PRESENT,
                source_notes=common_notes,
            )
        )

    add_metric(
        dimension="notification_rows",
        category="All published notification rows",
        value=len(rows),
    )
    for month, count in sorted(Counter(row.received_month for row in rows).items()):
        add_metric(
            dimension="notification_month",
            category=month.strftime("%Y-%m"),
            value=count,
            period_start=month,
            period_end=_month_end(month),
        )
    for dimension, counts in (
        ("sector", Counter(row.sector for row in rows)),
        ("affected_population_band", Counter(row.population_band for row in rows)),
        (
            "sensitive_data_field",
            Counter(row.sensitive_data or "Source field blank" for row in rows),
        ),
        (
            "individuals_informed",
            Counter(row.individuals_informed for row in rows),
        ),
        (
            "breach_nature",
            Counter(nature for row in rows for nature in row.breach_natures),
        ),
        (
            "incident_cause",
            Counter(cause for row in rows for cause in row.incident_causes),
        ),
    ):
        unit = (
            "category_observations"
            if dimension in {"breach_nature", "incident_cause"}
            else "notification_rows"
        )
        for category, count in sorted(counts.items()):
            add_metric(
                dimension=dimension,
                category=category,
                value=count,
                unit=unit,
            )
    return records


class CnilAdapter:
    source_id = "france_cnil"
    adapter_version = "1.0"
    normalization_version = "1.0"
    minimum_source_rows = 30_000
    earliest_month = EARLIEST_MONTH
    max_rows = 100_000
    max_response_bytes = 25_000_000

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def collect(self, *, observed_at: datetime | None = None) -> AdapterResult:
        observed_at = observed_at or datetime.now(UTC)
        with BoundedSourceClient(
            allowed_origins={
                "https://www.data.gouv.fr",
                "https://static.data.gouv.fr",
            },
            allowed_path_prefixes=(
                f"/api/1/datasets/{DATASET_ID}/",
                RESOURCE_PATH_PREFIX,
            ),
            max_response_bytes=self.max_response_bytes,
            total_deadline_seconds=180,
            transport=self.transport,
            user_agent=(
                "Mozilla/5.0 (compatible; BreachGazette/0.1; "
                "+https://github.com/slicedearth)"
            ),
        ) as client:
            metadata, _headers, _final_url = client.get_json(DATASET_API_URL)
            resource = _select_csv_resource(metadata)
            content, headers, _final_url = client.get_bytes(
                resource.url,
                accept="text/csv",
            )
        if "csv" not in headers.get("Content-Type", "").casefold():
            raise SourceClientError("CNIL resource returned an unexpected content type")
        rows = _parse_csv(
            content,
            coverage_end=resource.coverage_end,
            earliest_month=self.earliest_month,
        )
        if len(rows) < self.minimum_source_rows or len(rows) > self.max_rows:
            raise SourceClientError("CNIL source row count fell outside its reviewed bounds")
        checksum = sha256_hex(content)
        records = _aggregate_records(
            rows,
            resource=resource,
            checksum=checksum,
            observed_at=observed_at,
        )
        snapshot = source_snapshot(
            source_id=self.source_id,
            retrieved_at=observed_at,
            revision=(
                f"data-gouv-resource:{resource.resource_id}:"
                f"{resource.last_modified.isoformat()}"
            ),
            checksum=checksum,
            completeness=Completeness.COMPLETE,
            discovered=len(rows),
            accepted=len(rows),
            rejected=0,
            bounded_limit=self.max_rows,
            source_updated_at=resource.last_modified,
            notes=[
                f"Accepted {len(rows)} anonymized source rows.",
                f"Published {len(records)} privacy-minimised aggregate cells.",
                "Raw row combinations were not retained in durable state.",
                "The latest three months are excluded by the official source.",
                "Notification rows are not counts of unique breach incidents.",
            ],
        )
        return AdapterResult(
            source_id=self.source_id,
            records=records,
            snapshot=snapshot,
        )
