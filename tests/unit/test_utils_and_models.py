from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from breachgazette.clients.california import _date_observations
from breachgazette.clients.ipc_nsw import _cell_value, _parse_period
from breachgazette.clients.washington import _parse_date
from breachgazette.contracts import (
    DateObservation,
    OrganizationRole,
    SourceAnonymizedNotificationRecord,
    SourceRegulatoryRecord,
)
from breachgazette.contracts.enums import (
    Completeness,
    CoverageType,
    DatePrecision,
    EntityRole,
    LegalStatus,
    ValueOrigin,
    ValueState,
)
from breachgazette.contracts.models import ObservedValue
from breachgazette.utils import (
    canonical_json_bytes,
    normalize_organization_name,
    normalize_text,
    sanitize_public_url,
    sha256_hex,
    stable_id,
)


@given(st.text(max_size=80))
def test_name_normalization_is_deterministic(value: str) -> None:
    try:
        first = normalize_organization_name(value)
    except ValueError:
        return
    assert normalize_organization_name(value) == first


@given(st.dates())
def test_date_serialization_is_deterministic(value: date) -> None:
    assert canonical_json_bytes({"date": value}) == canonical_json_bytes({"date": value})


def test_text_and_name_normalization() -> None:
    assert normalize_text("  Curly\u2019s   name  ") == "Curly's name"
    assert normalize_organization_name("Éxample Health, Inc.") == "example health"
    with pytest.raises(ValueError, match="character limit"):
        normalize_text("x" * 4, maximum=3)


def test_canonical_hashes_and_ids_are_stable() -> None:
    left = {"b": 2, "a": [1, True]}
    right = {"a": [1, True], "b": 2}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert sha256_hex(left) == sha256_hex(right)
    assert stable_id("record", left) == stable_id("record", right)


def test_safe_url_decodes_nsw_safelink_without_contact_query() -> None:
    wrapped = (
        "https://aus01.safelinks.protection.outlook.com/"
        "?url=https%3A%2F%2Fagency.nsw.gov.au%2Fnotification%3Fx%3D1"
        "&data=person%40example.test"
    )
    assert sanitize_public_url(wrapped) == "https://agency.nsw.gov.au/notification?x=1"
    for unsafe in ("http://example.gov", "https://user:pass@example.gov", "javascript:alert(1)"):
        with pytest.raises(ValueError):
            sanitize_public_url(unsafe)


def test_observed_value_distinguishes_null_and_zero() -> None:
    assert ObservedValue(value=None, origin=ValueOrigin.SOURCE_OBSERVED).state == "null"
    assert ObservedValue(value=0, origin=ValueOrigin.SOURCE_OBSERVED).state == "zero"


def test_anonymized_notification_preserves_month_precision_without_an_entity() -> None:
    observed = datetime(2026, 1, 1, tzinfo=UTC)
    record = SourceAnonymizedNotificationRecord(
        source_id="example_anonymized",
        source_record_id="anonymous:2025-12:1",
        source_url="https://example.gov/open-data",
        source_revision="2025-12",
        source_checksum="a" * 64,
        source_completeness=Completeness.COMPLETE,
        source_retrieval_time=observed,
        local_first_observed_time=observed,
        local_last_observed_time=observed,
        parser_version="1.0",
        normalization_version="1.0",
        limitations=["The official source does not publish an organization name."],
        regulator="Example regulator",
        country="Example country",
        jurisdiction="National",
        reporting_scheme="Anonymous notification reporting",
        coverage_type=CoverageType.COMPLETE_ANONYMIZED_DATASET,
        dates=[
            DateObservation(
                meaning="regulator_submission_date",
                raw_value="2025-12",
                normalized_date=date(2025, 12, 1),
                precision=DatePrecision.MONTH,
                origin=ValueOrigin.SOURCE_OBSERVED,
                state=ValueState.PRESENT,
            )
        ],
        affected_population_band=ObservedValue(
            value="Between 0 and 5 people",
            origin=ValueOrigin.SOURCE_OBSERVED,
        ),
        individuals_informed=ObservedValue(
            value=True,
            origin=ValueOrigin.SOURCE_OBSERVED,
        ),
    )
    assert record.publication_level == "anonymized_notification"
    assert record.dates[0].precision == "month"
    assert "named_entity" not in record.model_dump()


def _regulatory_payload() -> dict[str, object]:
    observed = datetime(2026, 1, 1, tzinfo=UTC)
    return {
        "source_id": "oaic_regulatory",
        "source_record_id": "matter-event",
        "source_url": "https://www.oaic.gov.au/news/media-centre/example",
        "source_revision": "revision",
        "source_checksum": "a" * 64,
        "source_completeness": Completeness.SELECTIVE,
        "source_retrieval_time": observed,
        "local_first_observed_time": observed,
        "local_last_observed_time": observed,
        "parser_version": "1.0",
        "normalization_version": "1.0",
        "limitations": ["Selective timeline."],
        "regulator": "OAIC",
        "matter_id": "matter",
        "entity": OrganizationRole(
            source_name="Example Limited",
            normalized_name="example",
            role=EntityRole.ALLEGED_RESPONDENT,
            origin=ValueOrigin.MANUALLY_CURATED,
        ),
        "legal_status": LegalStatus.CIVIL_PROCEEDING_ALLEGATION,
        "source_title": "Proceeding filed",
        "source_publication_date": date(2026, 1, 1),
        "source_reported_event_date": date(2026, 1, 1),
        "status_wording": "The Commissioner alleges",
        "summary": "The Commissioner alleges a contravention.",
        "allegation": True,
        "finding": False,
    }


def test_regulatory_status_rejects_ambiguity_and_allegation_as_finding() -> None:
    payload = _regulatory_payload()
    payload["legal_status"] = LegalStatus.STATUS_UNKNOWN
    with pytest.raises(ValidationError, match="ambiguous"):
        SourceRegulatoryRecord.model_validate(payload)
    payload = _regulatory_payload()
    payload["finding"] = True
    with pytest.raises(ValidationError, match="both allegation and finding"):
        SourceRegulatoryRecord.model_validate(payload)


def test_california_and_nsw_date_and_cell_semantics() -> None:
    values = _date_observations("01/02/2025, 01/03/2025", "01/04/2025")
    assert [item.meaning for item in values] == [
        "occurrence_start",
        "occurrence_start",
        "regulator_submission_date",
    ]
    assert _date_observations("n/a", "01/04/2025")[0].state == "source_omitted"
    with pytest.raises(Exception, match="format changed"):
        _date_observations("future-format", "01/04/2025")
    assert _parse_date("2025-01-02T00:00:00") == date(2025, 1, 2)
    assert _parse_date("invalid") is None
    assert _parse_period("MNDB Scheme Data Snapshot July to December 2025") == (
        date(2025, 7, 1),
        date(2025, 12, 31),
    )
    assert _parse_period("MNDB Scheme Data Snapshot Jul\u2013Dec 2025") == (
        date(2025, 7, 1),
        date(2025, 12, 31),
    )
    assert _cell_value("31%5") == (31, "percent", ValueState.ESTIMATED)
    assert _cell_value("N/A") == (None, "count", ValueState.NOT_APPLICABLE)
