from __future__ import annotations

from datetime import date

import pytest

from breachgazette.contracts import AliasReviewDecision, DateObservation, SourceNotificationRecord
from breachgazette.entities import alias_decision_id, resolve_organizations
from breachgazette.entities.catalogue import AliasCatalogue
from breachgazette.quality.temporal import exclude_temporal_conflicts
from breachgazette.relationships import generate_candidates
from breachgazette.relationships.date_policy import date_keys


def test_reviewed_alias_source_ids_are_evidence_not_mapping_scope(notification_factory) -> None:
    decision = AliasReviewDecision(
        decision_id=alias_decision_id("Example Alias", "Example Canonical"),
        alias_name="Example Alias",
        canonical_name="Example Canonical",
        status="approved",
        source_ids=["washington"],
        evidence=["Synthetic supporting source evidence."],
        reviewed_on=date(2026, 1, 1),
        review_note="Synthetic reviewed decision.",
    )
    out_of_evidence_source = notification_factory(source_id="california", name="Example Alias")
    identities = resolve_organizations(
        [out_of_evidence_source],
        [],
        alias_catalogue=AliasCatalogue(decisions=(decision,)),
    )
    assert identities[0].canonical_name == "Example Canonical"
    assert identities[0].aliases[0].match_method == "curated_alias"


@pytest.mark.parametrize(
    "meaning",
    [
        "occurrence_start",
        "awareness_date",
        "regulator_submission_date",
        "public_notification_date",
    ],
)
def test_current_relationship_dates_compare_calendar_values_across_meanings(
    notification_factory,
    meaning,
) -> None:
    left = notification_factory(source_id="washington", record_id="wa:1")
    right = notification_factory(source_id="california", record_id="ca:1")
    right.dates[0].meaning = meaning
    candidate = generate_candidates([left, right])[0]
    assert candidate.relationship_class == "possibly_related_event"
    assert candidate.reasons[1].explanation == "At least one source-backed date is identical."
    assert bool(
        date_keys(left, policy="same_meaning_v1") & date_keys(right, policy="same_meaning_v1")
    ) is (meaning == "occurrence_start")
    right.dates[0].normalized_date = None
    right.dates[0].state = "source_conflict"
    assert generate_candidates([left, right]) == []


@pytest.mark.parametrize(
    "source,excluded",
    [
        ("california", 1),
        ("washington", 0),
        ("massachusetts", 0),
        ("nsw_public_notifications", 0),
    ],
)
def test_chronology_exclusions_remain_source_specific(
    notification_factory, source, excluded
) -> None:
    record = SourceNotificationRecord.model_validate(
        notification_factory(
            source_id=source,
            observed_date=date(2026, 2, 1),
        ).model_dump(exclude={"canonical_organization_id"})
    )
    record.dates.append(
        DateObservation(
            meaning="regulator_submission_date",
            normalized_date=date(2026, 1, 1),
            origin="source_observed",
            state="present",
        )
    )
    assert exclude_temporal_conflicts(record) == excluded
    assert (record.dates[0].normalized_date is None) is bool(excluded)
