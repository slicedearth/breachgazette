from __future__ import annotations

import csv
import json
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path

import httpx
import pytest
import yaml
from openpyxl import Workbook

from breachgazette.clients.base import SourceClientError
from breachgazette.clients.california import CaliforniaAdapter
from breachgazette.clients.hhs import HhsAdapter
from breachgazette.clients.ipc_nsw import NswAggregateAdapter, NswPublicNotificationsAdapter
from breachgazette.clients.oaic import EXPECTED_SHEETS, OaicNdbAdapter
from breachgazette.clients.oaic_regulatory import OaicRegulatoryAdapter
from breachgazette.clients.washington import MAIN_FIELDS, PII_FIELDS, WashingtonAdapter


def _json_response(value: object) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"Content-Type": "application/json"},
        content=json.dumps(value).encode(),
    )


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
