from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import yaml

from breachgazette.clients.annual_reports import FranceCnilAnnualAdapter, IrelandDpcAdapter
from breachgazette.clients.base import SourceClientError
from breachgazette.clients.european_regulatory import (
    FranceRegulatoryAdapter,
    UnitedKingdomRegulatoryAdapter,
)
from breachgazette.contracts import SourceRegulatoryRecord
from breachgazette.privacy.audit import audit_public_value

NOW = datetime(2026, 10, 11, tzinfo=UTC)


def test_site_fixture_metadata_matches_its_expanded_records() -> None:
    path = Path(__file__).resolve().parents[1] / "fixtures" / "site" / "publication.json"
    publication = json.loads(path.read_text(encoding="utf-8"))
    counts = publication["manifest"]["record_counts"]
    for key, records in (
        ("aggregate_metrics", "aggregates"),
        ("regulatory_actions", "regulatory_actions"),
    ):
        assert counts[key] == publication["stats"][key] == len(publication[records])
    implemented = {key for key, policy in publication["policies"].items() if policy["implemented"]}
    deferred = {policy["source_id"] for policy in publication["deferred_sources"]}
    assert not implemented & deferred


def html_transport(text: str) -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            text=text,
        )
    )


@pytest.mark.parametrize(
    ("number", "suffix", "expected"),
    [
        ("6,521", ", representing", 6521),
        ("6,521", " , representing", 6521),
        ("6,521", " representing", 6521),
        ("0", ", representing", 0),
    ],
)
def test_irish_headline_retains_whole_number(number: str, suffix: str, expected: int) -> None:
    body = f"<h1>{IrelandDpcAdapter.title_marker}</h1>"
    body += f"<p>Total valid breach notifications received in 2025 was {number}{suffix}</p>"
    result = IrelandDpcAdapter(transport=html_transport(body)).collect(observed_at=NOW)
    record = result.records[0]
    assert record.value.value == expected
    assert record.value.state == ("zero" if expected == 0 else "present")
    assert record.value.origin == "source_observed"
    assert record.reporting_period_start.isoformat() == "2025-01-01"
    assert record.dimension == "valid_breach_notifications_received"
    assert result.snapshot.completeness == "selective"
    assert result.snapshot.records_accepted == 1
    assert not audit_public_value(record, record_identity=record.source_record_id)


@pytest.mark.parametrize(
    "body",
    [
        "<p>Total valid breach notifications received in 2025 was 6,52, representing</p>",
        "<p>Total valid breach notifications received in 2025 was 6,5210, representing</p>",
        "<script>Total valid breach notifications received in 2025 "
        "was 6,521, representing</script>",
        "<p>Total valid breach notifications received in 2024 was 6,521, representing</p>",
        "<p>Total valid breach notifications received in 2025 was 6,521, representing</p>" * 2,
    ],
)
def test_irish_schema_drift_never_truncates_or_guesses(body: str) -> None:
    with pytest.raises(SourceClientError, match="markers changed"):
        IrelandDpcAdapter(
            transport=html_transport(
                f"<h1>{IrelandDpcAdapter.title_marker}</h1>{body}",
            )
        ).collect(observed_at=NOW)


def test_french_headline_preserves_source_adjustment() -> None:
    body = f"<h1>{FranceCnilAnnualAdapter.title_marker}</h1>"
    body += "<p>Parmi les 6&nbsp;167 violations de données notifiées à la CNIL,</p>"
    result = FranceCnilAnnualAdapter(transport=html_transport(body)).collect(observed_at=NOW)
    record = result.records[0]
    assert record.value.value == 6167
    assert record.dimension == "adjusted_breach_notifications_received"
    assert "excluding" in record.population_scope
    assert any("11,635" in note for note in record.source_notes)
    assert any("must not" in note for note in record.source_notes)
    assert not audit_public_value(record, record_identity=record.source_record_id)


def test_changed_french_adjustment_needs_review() -> None:
    body = f"<h1>{FranceCnilAnnualAdapter.title_marker}</h1>"
    body += "<p>Parmi les 6 200 violations de données notifiées à la CNIL,</p>"
    with pytest.raises(SourceClientError, match="review its scope"):
        FranceCnilAnnualAdapter(transport=html_transport(body)).collect(observed_at=NOW)


def decision_manifest(adapter, tmp_path: Path) -> tuple[Path, dict]:
    data = {
        "schema_version": "1.0",
        "source_id": adapter.source_id,
        "reviewed_at": "2026-10-11",
        "entries": [
            {
                "event_id": adapter.source_id.replace("_", "-") + "-example-2026",
                "matter_id": "example-matter",
                "entity": "Example Processor Limited",
                "official_url": adapter.origin + adapter.path_prefix + "example/",
                "expected_markers": ["Example Processor Limited", "fine imposed", "9 October 2026"],
                "source_title": "Example Processor Limited decision",
                "publication_date": "2026-10-10",
                "event_date": "2026-10-09",
                "legal_status": "administrative_fine",
                "status_wording": "Administrative fine imposed",
                "summary": "Synthetic regulatory decision for testing.",
            }
        ],
    }
    path = tmp_path / "decisions.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path, data


@pytest.mark.parametrize("adapter", [FranceRegulatoryAdapter, UnitedKingdomRegulatoryAdapter])
def test_regulatory_decisions_keep_status_role_dates_and_provenance(
    adapter, tmp_path: Path
) -> None:
    path, data = decision_manifest(adapter, tmp_path)
    text = "<p>Example Processor Limited: fine imposed on 9 October 2026</p>"
    result = adapter(manifest_path=path, transport=html_transport(text)).collect(observed_at=NOW)
    record = result.records[0]
    assert record.legal_status == "administrative_fine"
    assert record.finding is True and record.allegation is False
    assert record.entity.role == "regulator_named_entity"
    assert record.source_publication_date != record.source_reported_event_date
    assert record.source_revision == record.source_checksum[:16]
    assert len(record.source_checksum) == 64
    assert result.snapshot.completeness == "selective"
    assert not audit_public_value(record, record_identity=record.source_record_id)
    payload = record.model_dump()
    payload["finding"] = False
    with pytest.raises(ValueError, match="must retain"):
        SourceRegulatoryRecord.model_validate(payload)
    data["entries"][0]["summary"] = "A revised synthetic description."
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    changed = adapter(manifest_path=path, transport=html_transport(text)).collect(observed_at=NOW)
    assert changed.snapshot.checksum_sha256 != result.snapshot.checksum_sha256


@pytest.mark.parametrize("change", ["source", "duplicate", "date", "future", "status", "empty"])
def test_invalid_regulatory_manifests_fail_before_fetch(change: str, tmp_path: Path) -> None:
    adapter = UnitedKingdomRegulatoryAdapter
    path, data = decision_manifest(adapter, tmp_path)
    if change == "source":
        data["source_id"] = "unrelated"
    elif change == "duplicate":
        data["entries"] *= 2
    elif change == "date":
        data["entries"][0]["event_date"] = "2026-10-11"
    elif change == "future":
        data["reviewed_at"] = "2099-01-01"
    elif change == "status":
        data["entries"][0]["legal_status"] = "civil_penalty_order"
    else:
        data["entries"][0]["expected_markers"][0] = " "
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    def reject_fetch(_request):
        pytest.fail("invalid manifest must not retrieve any source")

    with pytest.raises(SourceClientError, match="manifest"):
        adapter(manifest_path=path, transport=httpx.MockTransport(reject_fetch)).collect(
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    "text",
    [
        "<p>Example Processor Limited on 9 October 2026</p>",
        "<script>Example Processor Limited: fine imposed on 9 October 2026</script>",
    ],
)
def test_regulatory_marker_drift_fails_closed(text: str, tmp_path: Path) -> None:
    path, _data = decision_manifest(UnitedKingdomRegulatoryAdapter, tmp_path)
    with pytest.raises(SourceClientError, match="markers changed"):
        UnitedKingdomRegulatoryAdapter(manifest_path=path, transport=html_transport(text)).collect(
            observed_at=NOW,
        )


def test_new_sources_are_consistent_across_required_catalogues() -> None:
    from breachgazette.monitoring import load_monitoring_catalogue
    from breachgazette.pipeline import ADAPTERS
    from breachgazette.policies import load_source_policies
    from breachgazette.quality.gates import REQUIRED_SOURCES

    implemented = {key for key, policy in load_source_policies().items() if policy.implemented}
    assert (
        implemented == set(ADAPTERS) == REQUIRED_SOURCES == set(load_monitoring_catalogue().sources)
    )
