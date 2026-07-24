from __future__ import annotations

import csv
import json
from datetime import date, datetime
from io import BytesIO, StringIO
from pathlib import Path

import httpx
import pytest
import yaml
from openpyxl import Workbook

from breachgazette.clients.base import SourceClientError
from breachgazette.clients.california import CaliforniaAdapter
from breachgazette.clients.france_cnil import (
    DATASET_ID,
    EXPECTED_DATASET_TITLE,
    CnilAdapter,
)
from breachgazette.clients.france_cnil import (
    EXPECTED_HEADERS as CNIL_HEADERS,
)
from breachgazette.clients.hhs import HhsAdapter
from breachgazette.clients.ipc_nsw import NswAggregateAdapter, NswPublicNotificationsAdapter
from breachgazette.clients.massachusetts import (
    EXPECTED_HEADERS,
    MassachusettsAdapter,
    _parse_rows,
)
from breachgazette.clients.oaic import EXPECTED_SHEETS, OaicNdbAdapter
from breachgazette.clients.oaic_regulatory import OaicRegulatoryAdapter
from breachgazette.clients.washington import MAIN_FIELDS, PII_FIELDS, WashingtonAdapter
from breachgazette.privacy.audit import audit_public_value


def _json_response(value: object) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"Content-Type": "application/json"},
        content=json.dumps(value).encode(),
    )


def _cnil_fixture(*, license_id: str = "lov2") -> tuple[dict[str, object], bytes]:
    output = StringIO()
    writer = csv.writer(output, delimiter=";", lineterminator="\n")
    writer.writerow(["Extraction générée le 15 janvier 2026", *([""] * 8)])
    writer.writerow(CNIL_HEADERS)
    source_row = [
        "2025-12",
        "Santé humaine et action sociale",
        "Perte de la confidentialité,Perte de la disponibilité",
        "Entre 51 et 300 personnes",
        "Etat civil (ex : nom, sexe, date de naissance, âge...)",
        "Oui",
        "Piratage, logiciel malveillant (par exemple rançongiciel) et/ou hameçonnage",
        "Acte externe malveillant,Acte interne accidentel",
        "Oui, les personnes ont été informées",
    ]
    writer.writerow(source_row)
    writer.writerow(source_row)
    content = output.getvalue().encode("cp1252")
    title = "opencnil-violationsdcpnotifiees-20251231.csv"
    resource_url = (
        "https://static.data.gouv.fr/resources/"
        "notifications-a-la-cnil-de-violations-de-donnees-a-caractere-personnel/"
        f"20260115-120000/{title}"
    )
    metadata: dict[str, object] = {
        "id": DATASET_ID,
        "title": EXPECTED_DATASET_TITLE,
        "license": license_id,
        "private": False,
        "frequency": "quarterly",
        "last_update": "2026-01-15T12:00:00+00:00",
        "organization": {"name": "CNIL"},
        "resources": [
            {
                "id": "11111111-2222-3333-4444-555555555555",
                "format": "csv",
                "title": title,
                "url": resource_url,
                "filesize": len(content),
                "last_modified": "2026-01-15T12:00:00+00:00",
            }
        ],
    }
    return metadata, content


def test_cnil_anonymous_rows_are_counted_without_row_level_publication(
    observed_at: datetime,
) -> None:
    metadata, content = _cnil_fixture()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.data.gouv.fr":
            return _json_response(metadata)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/csv"},
            content=content,
        )

    adapter = CnilAdapter(transport=httpx.MockTransport(handler))
    adapter.minimum_source_rows = 1
    adapter.earliest_month = date(2025, 12, 1)
    result = adapter.collect(observed_at=observed_at)

    total = next(
        record
        for record in result.records
        if record.dimension == "notification_rows"
    )
    month = next(
        record
        for record in result.records
        if record.dimension == "notification_month"
    )
    natures = {
        record.category: record.value.value
        for record in result.records
        if record.dimension == "breach_nature"
    }
    assert total.value.value == 2
    assert month.category == "2025-12"
    assert month.value.value == 2
    assert natures == {
        "Perte de la confidentialité": 2,
        "Perte de la disponibilité": 2,
    }
    assert result.snapshot.records_discovered == 2
    assert result.snapshot.records_accepted == 2
    assert all(record.publication_level == "anonymized_notification" for record in result.records)
    assert all(record.record_type == "aggregate" for record in result.records)
    assert not [
        finding
        for record in result.records
        for finding in audit_public_value(
            record,
            record_identity=record.source_record_id,
        )
    ]


def test_cnil_metadata_and_schema_drift_fail_closed(observed_at: datetime) -> None:
    metadata, content = _cnil_fixture(license_id="changed")
    adapter = CnilAdapter(
        transport=httpx.MockTransport(lambda _request: _json_response(metadata))
    )
    adapter.minimum_source_rows = 1
    adapter.earliest_month = date(2025, 12, 1)
    with pytest.raises(SourceClientError, match="licence"):
        adapter.collect(observed_at=observed_at)

    valid_metadata, _valid_content = _cnil_fixture()
    changed = content.replace(
        CNIL_HEADERS[0].encode("cp1252"),
        b"Changed header",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.data.gouv.fr":
            return _json_response(valid_metadata)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/csv"},
            content=changed,
        )

    schema_adapter = CnilAdapter(transport=httpx.MockTransport(handler))
    schema_adapter.minimum_source_rows = 1
    schema_adapter.earliest_month = date(2025, 12, 1)
    with pytest.raises(SourceClientError, match="schema"):
        schema_adapter.collect(observed_at=observed_at)


def test_california_csv_handles_duplicates_multiple_dates_and_na(observed_at: datetime) -> None:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Organization Name", "Date(s) of Breach  (if known)", "Reported Date"])
    writer.writerow(["Example Services", "01/01/2025, 01/02/2025", "01/03/2025"])
    writer.writerow(["Example Services", "01/01/2025, 01/02/2025", "01/03/2025"])
    writer.writerow(["Other Foundation", "n/a", "01/04/2025"])
    writer.writerow(["", "", "01/05/2025"])

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Type": "text/csv"},
            content=output.getvalue().encode(),
        )
    )
    result = CaliforniaAdapter(transport=transport).collect(observed_at=observed_at)
    assert len(result.records) == 4
    assert result.records[0].source_record_id.endswith(":1")
    assert result.records[1].source_record_id.endswith(":2")
    assert len(result.records[0].dates) == 3
    assert result.records[2].dates[0].state == "source_omitted"
    assert all(record.source_detail_url is None for record in result.records)
    assert result.records[3].named_entity.state == "source_omitted"
    assert result.records[3].named_entity.role == "unknown"


def test_california_future_schema_and_malformed_dates_fail(observed_at: datetime) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Type": "text/csv"},
            content=b"Changed,Header\nvalue,value\n",
        )
    )
    with pytest.raises(SourceClientError, match="schema"):
        CaliforniaAdapter(transport=transport).collect(observed_at=observed_at)


def test_california_source_date_after_submission_is_retained_but_not_normalized(
    observed_at: datetime,
) -> None:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Organization Name", "Date(s) of Breach  (if known)", "Reported Date"])
    writer.writerow(["Example Services", "11/20/2027, 12/14/2023", "07/03/2024"])
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Type": "text/csv"},
            content=output.getvalue().encode(),
        )
    )

    record = CaliforniaAdapter(transport=transport).collect(observed_at=observed_at).records[0]

    assert record.dates[0].raw_value == "11/20/2027"
    assert record.dates[0].normalized_date is None
    assert record.dates[0].state == "source_conflict"
    assert record.dates[1].normalized_date.isoformat() == "2023-12-14"
    assert any("post-dates the regulator submission date" in item for item in record.limitations)


def test_washington_schema_join_counts_and_roles(observed_at: datetime) -> None:
    metadata = {
        "columns": [{"fieldName": field} for field in MAIN_FIELDS],
        "attribution": "Washington State Attorney General's Office Consumer Protection Division",
        "rowsUpdatedAt": 1_735_689_600,
    }
    pii_metadata = {
        "columns": [{"fieldName": field} for field in PII_FIELDS],
        "rowsUpdatedAt": 1_735_689_600,
    }
    main = {
        "id": "100",
        "name": "Example Services",
        "dateaware": "2025-01-02T00:00:00.000",
        "datesubmitted": "2025-01-03T00:00:00.000",
        "datestart": "2025-01-01T00:00:00.000",
        "dateend": "2025-01-02T00:00:00.000",
        "databreachcause": "Cyberattack",
        "cyberattacktype": "Ransomware",
        "washingtoniansaffected": "650",
        "industrytype": "Healthcare",
    }
    pii = [
        {"id": "100", "informationtype": "Name"},
        {"id": "100", "informationtype": "Health information"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/views/sb4j-ca4h"):
            return _json_response(metadata)
        if request.url.path.endswith("/api/views/padd-mby7"):
            return _json_response(pii_metadata)
        dataset = "main" if "sb4j-ca4h" in request.url.path else "pii"
        if request.url.params.get("$select") == "count(*) as count":
            return _json_response([{"count": "1" if dataset == "main" else "2"}])
        return _json_response([main] if dataset == "main" else pii)

    result = WashingtonAdapter(transport=httpx.MockTransport(handler)).collect(
        observed_at=observed_at
    )
    record = result.records[0]
    assert record.named_entity.role == "notifying_entity"
    assert record.affected_population.count == 650
    assert [item.source_label for item in record.information_categories] == [
        "Health information",
        "Name",
    ]
    assert result.snapshot.records_accepted == 1


def test_washington_schema_drift_is_rejected(observed_at: datetime) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/api/views/" in request.url.path:
            return _json_response({"columns": [], "attribution": "changed"})
        raise AssertionError("row endpoint should not be reached")

    with pytest.raises(SourceClientError, match="schema"):
        WashingtonAdapter(transport=httpx.MockTransport(handler)).collect(observed_at=observed_at)


def test_massachusetts_rows_preserve_roles_counts_flags_and_dates(
    observed_at: datetime,
) -> None:
    row = dict.fromkeys(EXPECTED_HEADERS, "No")
    row.update(
        {
            "Breach Number": "2026-1234",
            "Date Reported To OCA": "23-Jul-26",
            "Reporting Organization Name": "Example Health Services",
            "Reporting Organization Type": "Health Care",
            "MA Residents Affected": "1,250",
            "SSN Breached": "Yes",
            "Medical Records Breached": "Yes",
        }
    )
    placeholder: dict[str, str] = {
        **dict.fromkeys(EXPECTED_HEADERS, "-"),
        "Breach Number": "2026- 9999",
    }
    duplicate: dict[str, str] = {
        **dict.fromkeys(EXPECTED_HEADERS, ""),
        "Breach Number": "2026- 9998",
        "Date Reported To OCA": "23-Jul-26",
        "Reporting Organization Name": "DUPLICATE OF 2026-9997",
    }
    records = _parse_rows(
        {2026: [row, placeholder, duplicate]},
        checksum="a" * 64,
        observed_at=observed_at,
    )
    record = records[0]
    assert record.source_record_id == "ma:2026-1234"
    assert record.named_entity.role == "notifying_entity"
    assert record.affected_population.count == 1_250
    assert record.dates[0].normalized_date.isoformat() == "2026-07-23"
    assert [category.normalized_label for category in record.information_categories] == [
        "social_security_number",
        "medical_records",
    ]
    assert record.source_detail_url is not None


def test_massachusetts_adapter_is_bounded_and_rejects_changed_flags(
    observed_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = dict.fromkeys(EXPECTED_HEADERS, "No")
    valid.update(
        {
            "Breach Number": "2025-0001",
            "Date Reported To OCA": "02-Jan-25",
            "Reporting Organization Name": "Example Services",
            "Reporting Organization Type": "Professional Services",
            "MA Residents Affected": "12",
        }
    )
    reports = iter(
        [
            [{**valid, "Breach Number": f"{year}-0001"}]
            for year in (2024, 2025, 2026)
        ]
    )
    monkeypatch.setattr(
        "breachgazette.clients.massachusetts._extract_rows",
        lambda _content: next(reports),
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=b"%PDF synthetic fixture",
        )
    )
    result = MassachusettsAdapter(transport=transport).collect(observed_at=observed_at)
    assert result.snapshot.records_discovered == 3
    assert result.snapshot.records_accepted == 3
    assert result.snapshot.bounded_limit == 10_000
    assert result.snapshot.revision.startswith("annual-reports-2024-2026:")

    invalid = {**valid, "SSN Breached": "Unknown"}
    with pytest.raises(SourceClientError, match="flag"):
        _parse_rows({2025: [invalid]}, checksum="b" * 64, observed_at=observed_at)


def test_massachusetts_preserves_reviewed_sparse_and_character_spaced_rows(
    observed_at: datetime,
) -> None:
    sparse = dict.fromkeys(EXPECTED_HEADERS, "")
    sparse.update(
        {
            "Breach Number": "2024-94",
            "Date Reported To OCA": "17-Jan-24",
            "Reporting Organization Name": "easternbank",
        }
    )
    spaced = dict.fromkeys(EXPECTED_HEADERS, "N o")
    spaced.update(
        {
            "Breach Number": "2024-2164",
            "Date Reported To OCA": "09-Dec-24",
            "Reporting Organization Name": "Webster Five Cents Savings Bank",
            "Reporting Organization Type": "B a n k s & C r e d i t U n i o n s",
            "MA Residents Affected": "3",
            "Credit/Debit Numbers Breached": "Y e s",
        }
    )

    records = _parse_rows(
        {2024: [sparse, spaced]},
        checksum="c" * 64,
        observed_at=observed_at,
    )

    assert records[0].affected_population.state == "source_omitted"
    assert records[0].affected_population.count is None
    assert "omitted all reviewed information-category flags" in " ".join(
        records[0].limitations
    )
    assert records[1].industry == "Banks & Credit Unions"
    assert records[1].information_categories[0].normalized_label == "credit_debit_card"


def test_massachusetts_withholds_address_like_reporting_organization(
    observed_at: datetime,
) -> None:
    row = dict.fromkeys(EXPECTED_HEADERS, "No")
    row.update(
        {
            "Breach Number": "2024-0944",
            "Date Reported To OCA": "15-May-24",
            "Reporting Organization Name": "123 Example Street",
            "Reporting Organization Type": "Professional Services",
            "MA Residents Affected": "1",
        }
    )

    record = _parse_rows(
        {2024: [row]},
        checksum="d" * 64,
        observed_at=observed_at,
    )[0]

    assert record.named_entity.source_name == "Reporting organization withheld"
    assert record.named_entity.normalized_name == (
        "reporting-organization-withheld-ma-2024-0944"
    )
    assert record.named_entity.role == "unknown"
    assert record.named_entity.origin == "normalized"
    assert record.named_entity.state == "source_omitted"
    assert "123 Example Street" not in record.model_dump_json()
    assert "public-output privacy detector" in " ".join(record.limitations)


def test_nsw_register_preserves_dates_links_and_window_state(
    observed_at: datetime,
) -> None:
    html = """
      <main>
        <table><thead><tr>
          <th>Agency Public Notification Date</th><th>Agency Date of Incident</th>
          <th>Agency Name</th><th>Notification</th>
        </tr></thead><tbody><tr>
          <td>1 January 2026</td><td>20 December 2025</td><td>Example Agency</td>
          <td><a href="https://agency.nsw.gov.au/notice">Open</a></td>
        </tr></tbody></table>
        <table><thead><tr>
          <th>Agency Public Notification Date</th><th>Agency Date of Incident</th>
          <th>Agency Name</th><th>Notification</th>
        </tr></thead><tbody><tr>
          <td>1 January 2025</td><td>20 December 2024</td><td>Past Agency</td>
          <td></td>
        </tr></tbody></table>
      </main>
    """
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200, headers={"Content-Type": "text/html"}, content=html.encode()
        )
    )
    result = NswPublicNotificationsAdapter(transport=transport).collect(observed_at=observed_at)
    assert [record.register_window_state for record in result.records] == [
        "current",
        "expired",
    ]
    first = result.records[0]
    assert first.named_entity.source_name == "Example Agency"
    assert str(first.source_detail_url) == "https://agency.nsw.gov.au/notice"
    assert [item.meaning for item in first.dates] == [
        "public_notification_date",
        "occurrence_start",
    ]


def _oaic_workbook() -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name in EXPECTED_SHEETS:
        sheet = workbook.create_sheet(name)
        sheet.append(["Heading", None])
    workbook[EXPECTED_SHEETS[1]].append(["July", 101])
    workbook[EXPECTED_SHEETS[1]].append(["Malicious or criminal attack", 60])
    workbook[EXPECTED_SHEETS[2]].append(["Individuals worldwide affected", None])
    workbook[EXPECTED_SHEETS[2]].append(["1,001 to 5,000", 40])
    workbook[EXPECTED_SHEETS[3]].append(["Contact information", "31%"])
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def test_oaic_workbook_uses_exact_sheets_period_and_scopes(observed_at: datetime) -> None:
    xlsx = _oaic_workbook()
    package = {
        "success": True,
        "result": {
            "license_id": "cc-by-4.0",
            "metadata_modified": "2026-06-29",
            "resources": [
                {
                    "id": "resource",
                    "format": "XLSX",
                    "name": "NDB Data 1 July 2025 to 31 Dec 2025",
                    "url": "https://data.gov.au/data/dataset/resource.xlsx",
                }
            ],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "/api/3/action/" in request.url.path:
            return _json_response(package)
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            },
            content=xlsx,
        )

    result = OaicNdbAdapter(transport=httpx.MockTransport(handler)).collect(observed_at=observed_at)
    assert result.snapshot.records_accepted == 4
    assert result.records[0].reporting_period_start.isoformat() == "2025-07-01"
    assert any(
        record.population_scope.startswith("Individuals worldwide") for record in result.records
    )
    assert any(record.unit == "percent" for record in result.records)


def test_oaic_regulatory_manifest_preserves_allegation_status(
    tmp_path: Path, observed_at: datetime
) -> None:
    manifest = {
        "schema_version": "1.0",
        "reviewed_at": "2026-01-01",
        "entries": [
            {
                "event_id": "example-proceeding",
                "matter_id": "example",
                "official_url": "https://www.oaic.gov.au/news/media-centre/example",
                "expected_marker": "Commissioner alleges",
                "legal_status": "civil_proceeding_allegation",
                "entity_role": "alleged_respondent",
                "entity": "Example Limited",
                "source_title": "Proceeding filed",
                "publication_date": "2026-01-01",
                "event_date": "2026-01-01",
                "status_wording": "The Commissioner alleges",
                "summary": "The Commissioner alleges a contravention.",
            }
        ],
    }
    path = tmp_path / "manifest.yml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<html>Commissioner alleges</html>",
        )
    )
    result = OaicRegulatoryAdapter(transport=transport, manifest_path=path).collect(
        observed_at=observed_at
    )
    action = result.records[0]
    assert action.legal_status == "civil_proceeding_allegation"
    assert action.allegation is True
    assert action.finding is False


def test_hhs_and_changed_nsw_snapshot_fail_explicitly(observed_at: datetime) -> None:
    with pytest.raises(SourceClientError, match="deferred"):
        HhsAdapter().collect()
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<main>No reviewed snapshot</main>",
        )
    )
    with pytest.raises(SourceClientError, match="omitted snapshot"):
        NswAggregateAdapter(transport=transport).collect(observed_at=observed_at)
