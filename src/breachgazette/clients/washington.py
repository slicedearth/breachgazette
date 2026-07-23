"""Fixed-schema Socrata adapter for Washington breach notifications."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from urllib.parse import urlencode

import httpx

from breachgazette.clients.base import (
    AdapterResult,
    BoundedSourceClient,
    SourceClientError,
    source_snapshot,
)
from breachgazette.contracts import (
    BreachCause,
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
from breachgazette.utils import (
    canonical_json_bytes,
    normalize_organization_name,
    normalize_text,
    sha256_hex,
)

MAIN_ID = "sb4j-ca4h"
PII_ID = "padd-mby7"
ORIGIN = "https://data.wa.gov"
MAIN_FIELDS = (
    "dateaware",
    "datesubmitted",
    "databreachcause",
    "datestart",
    "dateend",
    "name",
    "id",
    "cyberattacktype",
    "washingtoniansaffected",
    "industrytype",
    "businesstype",
    "year",
    "yeartext",
    "washingtoniansaffectedrange",
    "breachlifecyclerange",
    "entitystate",
)
PII_FIELDS = ("id", "informationtype")


def _parse_date(raw: object) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _date_item(meaning: str, raw: object) -> DateObservation:
    text = str(raw) if raw not in {None, ""} else None
    normalized = _parse_date(raw)
    return DateObservation(
        meaning=meaning,
        raw_value=text,
        normalized_date=normalized,
        origin=ValueOrigin.SOURCE_OBSERVED,
        state=ValueState.PRESENT if text else ValueState.SOURCE_OMITTED,
    )


class WashingtonAdapter:
    source_id = "washington"
    adapter_version = "1.0"
    normalization_version = "1.0"
    max_rows = 10_000
    page_size = 500

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    @staticmethod
    def _metadata_url(dataset_id: str) -> str:
        return f"{ORIGIN}/api/views/{dataset_id}"

    @staticmethod
    def _resource_url(dataset_id: str, query: dict[str, str | int]) -> str:
        return f"{ORIGIN}/resource/{dataset_id}.json?{urlencode(query)}"

    def _fetch_rows(
        self,
        client: BoundedSourceClient,
        dataset_id: str,
        fields: tuple[str, ...],
    ) -> list[dict[str, object]]:
        count_payload, _headers, _url = client.get_json(
            self._resource_url(dataset_id, {"$select": "count(*) as count"})
        )
        if not isinstance(count_payload, list) or len(count_payload) != 1:
            raise SourceClientError("Washington count response changed")
        count = int(count_payload[0]["count"])
        if count <= 0 or count > self.max_rows:
            raise SourceClientError("Washington row count was empty or exceeded its bound")
        rows: list[dict[str, object]] = []
        for offset in range(0, count, self.page_size):
            payload, _headers, _url = client.get_json(
                self._resource_url(
                    dataset_id,
                    {
                        "$select": ",".join(fields),
                        "$order": "id ASC",
                        "$limit": self.page_size,
                        "$offset": offset,
                    },
                )
            )
            if not isinstance(payload, list):
                raise SourceClientError("Washington page was not a JSON array")
            rows.extend(row for row in payload if isinstance(row, dict))
        if len(rows) != count:
            raise SourceClientError("Washington pagination did not reconcile with count")
        return rows

    def collect(self, *, observed_at: datetime | None = None) -> AdapterResult:
        observed_at = observed_at or datetime.now(UTC)
        with BoundedSourceClient(
            allowed_origins={ORIGIN},
            allowed_path_prefixes=("/api/views/", "/resource/"),
            max_response_bytes=12_000_000,
            total_deadline_seconds=180,
            transport=self.transport,
        ) as client:
            main_metadata, _headers, _url = client.get_json(self._metadata_url(MAIN_ID))
            pii_metadata, _headers, _url = client.get_json(self._metadata_url(PII_ID))
            if not isinstance(main_metadata, dict) or not isinstance(pii_metadata, dict):
                raise SourceClientError("Washington metadata response changed")
            main_schema = tuple(
                column.get("fieldName")
                for column in main_metadata.get("columns", [])
                if isinstance(column, dict)
            )
            pii_schema = tuple(
                column.get("fieldName")
                for column in pii_metadata.get("columns", [])
                if isinstance(column, dict)
            )
            missing_main = set(MAIN_FIELDS) - set(main_schema)
            missing_pii = set(PII_FIELDS) - set(pii_schema)
            if missing_main or missing_pii:
                raise SourceClientError("Washington source schema changed")
            if main_metadata.get("attribution") != (
                "Washington State Attorney General's Office Consumer Protection Division"
            ):
                raise SourceClientError("Washington source attribution changed")
            main_rows = self._fetch_rows(client, MAIN_ID, MAIN_FIELDS)
            pii_rows = self._fetch_rows(client, PII_ID, PII_FIELDS)

        information_by_id: dict[str, list[str]] = defaultdict(list)
        for row in pii_rows:
            record_id = str(row.get("id", "")).strip()
            information_type = normalize_text(str(row.get("informationtype", "")), maximum=300)
            if (
                record_id
                and information_type
                and information_type not in information_by_id[record_id]
            ):
                information_by_id[record_id].append(information_type)
        identifiers = [str(row.get("id", "")).strip() for row in main_rows]
        if len(identifiers) != len(set(identifiers)) or any(
            not identifier for identifier in identifiers
        ):
            raise SourceClientError("Washington source IDs were missing or duplicated")
        checksum = sha256_hex(canonical_json_bytes([main_rows, pii_rows]))
        revision = f"{main_metadata.get('rowsUpdatedAt')}:{pii_metadata.get('rowsUpdatedAt')}"
        source_updated_at = datetime.fromtimestamp(
            min(
                int(main_metadata["rowsUpdatedAt"]),
                int(pii_metadata["rowsUpdatedAt"]),
            ),
            tz=UTC,
        )
        records: list[RecordProvenance] = []
        for row in main_rows:
            source_id = str(row["id"])
            name = normalize_text(str(row.get("name", "")), maximum=500)
            if not name:
                raise SourceClientError("Washington record omitted notifying entity name")
            affected_raw = row.get("washingtoniansaffected")
            affected = int(float(str(affected_raw))) if affected_raw not in {None, ""} else None
            cause = normalize_text(str(row.get("databreachcause", "")), maximum=200)
            subtype = normalize_text(str(row.get("cyberattacktype", "")), maximum=200)
            records.append(
                SourceNotificationRecord(
                    source_id=self.source_id,
                    source_record_id=f"wa:{source_id}",
                    source_url=f"{ORIGIN}/d/{MAIN_ID}",
                    source_revision=revision,
                    source_checksum=checksum,
                    source_completeness=Completeness.COMPLETE,
                    source_retrieval_time=observed_at,
                    local_first_observed_time=observed_at,
                    local_last_observed_time=observed_at,
                    parser_version=self.adapter_version,
                    normalization_version=self.normalization_version,
                    limitations=[
                        "The named entity is the notifier, not necessarily where the event "
                        "occurred.",
                        "Affected counts may be estimated.",
                    ],
                    regulator="Washington State Attorney General's Office",
                    jurisdiction="Washington",
                    reporting_scheme="Washington data breach notification laws",
                    publication_level=PublicationLevel.NAMED_NOTIFICATION,
                    coverage_type=CoverageType.COMPLETE_PUBLISHED_DATASET,
                    named_entity=OrganizationRole(
                        source_name=name,
                        normalized_name=normalize_organization_name(name),
                        role=EntityRole.NOTIFYING_ENTITY,
                        origin=ValueOrigin.SOURCE_OBSERVED,
                    ),
                    dates=[
                        _date_item("awareness_date", row.get("dateaware")),
                        _date_item("regulator_submission_date", row.get("datesubmitted")),
                        _date_item("occurrence_start", row.get("datestart")),
                        _date_item("occurrence_end", row.get("dateend")),
                    ],
                    affected_population=PopulationObservation(
                        count=affected,
                        scope="Washington residents",
                        estimated=True,
                        origin=ValueOrigin.SOURCE_OBSERVED,
                        state=ValueState.ESTIMATED
                        if affected is not None
                        else ValueState.SOURCE_OMITTED,
                    ),
                    information_categories=[
                        InformationCategory(
                            source_label=category,
                            normalized_label=category,
                            origin=ValueOrigin.SOURCE_OBSERVED,
                        )
                        for category in sorted(information_by_id[source_id])
                    ],
                    breach_cause=BreachCause(
                        source_label=cause or None,
                        normalized_label=cause or None,
                        subtype=subtype or None,
                        origin=ValueOrigin.SOURCE_OBSERVED,
                        state=ValueState.PRESENT if cause else ValueState.SOURCE_OMITTED,
                    ),
                    industry=normalize_text(str(row.get("industrytype", "")), maximum=200) or None,
                    register_window_state="not_applicable",
                )
            )
        snapshot = source_snapshot(
            source_id=self.source_id,
            retrieved_at=observed_at,
            revision=revision,
            checksum=checksum,
            completeness=Completeness.COMPLETE,
            discovered=len(main_rows),
            accepted=len(records),
            rejected=0,
            bounded_limit=self.max_rows,
            source_updated_at=source_updated_at,
            notes=[
                f"Joined {len(pii_rows)} one-to-many personal-information rows.",
                "Dataset-specific licence identifier was absent at retrieval.",
            ],
        )
        return AdapterResult(source_id=self.source_id, records=records, snapshot=snapshot)
