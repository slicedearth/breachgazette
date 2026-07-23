from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from breachgazette.compare import compare_records
from breachgazette.contracts.enums import Completeness
from breachgazette.entities import (
    alias_decision_id,
    load_alias_catalogue,
    propose_alias_reviews,
    resolve_organizations,
)
from breachgazette.relationships import (
    apply_relationship_decisions,
    generate_candidates,
    load_relationship_catalogue,
    relationship_decision_id,
)
from breachgazette.utils import canonical_json_bytes

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "reviews"


def test_exact_aliases_resolve_and_false_fuzzy_names_do_not(notification_factory) -> None:
    exact = notification_factory(record_id="a", name="Example Health Limited")
    variant = notification_factory(
        source_id="california",
        record_id="b",
        name="Example Health Ltd",
    )
    false_match = notification_factory(
        source_id="california",
        record_id="c",
        name="Example Healthy Living",
    )
    identities = resolve_organizations([exact, variant, false_match], [])
    assert len(identities) == 2
    assert sorted(len(identity.aliases) for identity in identities) == [1, 2]


def test_parent_and_subsidiary_remain_separate(notification_factory) -> None:
    parent = notification_factory(record_id="a", name="Example Holdings")
    child = notification_factory(record_id="b", name="Example Health Services")
    assert len(resolve_organizations([parent, child], [])) == 2


def test_reviewed_alias_catalogue_merges_only_approved_decisions(
    tmp_path: Path,
    notification_factory,
) -> None:
    path = tmp_path / "aliases.yml"
    decision_id = alias_decision_id("Example Health Services", "Example Health Group")
    path.write_text(
        f"""
schema_version: "2.0"
decisions:
  - decision_id: "{decision_id}"
    alias_name: "Example Health Services"
    canonical_name: "Example Health Group"
    status: approved
    source_ids: [california, washington]
    evidence:
      - "Official source records identify the reviewed legal name."
    reviewed_on: 2026-01-01
    review_note: "Synthetic reviewed decision for deterministic testing."
""".lstrip(),
        encoding="utf-8",
    )
    catalogue = load_alias_catalogue(path)
    alias = notification_factory(name="Example Health Services")
    canonical = notification_factory(
        source_id="california",
        record_id="california:1",
        name="Example Health Group",
    )
    identities = resolve_organizations(
        [alias, canonical],
        [],
        alias_catalogue=catalogue,
    )
    assert len(identities) == 1
    assert identities[0].canonical_name == "Example Health Group"
    reviewed = next(
        alias for alias in identities[0].aliases if alias.confidence_class == "reviewed"
    )
    assert decision_id in reviewed.supporting_evidence[0]


def test_alias_catalogue_rejects_chains(tmp_path: Path) -> None:
    first_id = alias_decision_id("Example One", "Example Two")
    second_id = alias_decision_id("Example Two", "Example Three")
    path = tmp_path / "aliases.yml"
    path.write_text(
        f"""
schema_version: "2.0"
decisions:
  - decision_id: "{first_id}"
    alias_name: "Example One"
    canonical_name: "Example Two"
    status: approved
    source_ids: [washington]
    evidence: ["Reviewed source evidence."]
    reviewed_on: 2026-01-01
    review_note: "First synthetic decision."
  - decision_id: "{second_id}"
    alias_name: "Example Two"
    canonical_name: "Example Three"
    status: approved
    source_ids: [california]
    evidence: ["Reviewed source evidence."]
    reviewed_on: 2026-01-01
    review_note: "Second synthetic decision."
""".lstrip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="chains"):
        load_alias_catalogue(path)


def test_alias_proposals_are_private_leads_not_resolution_decisions(
    notification_factory,
) -> None:
    left = notification_factory(name="Example Health")
    right = notification_factory(
        source_id="california",
        record_id="california:1",
        name="Example Health Services",
    )
    proposals = propose_alias_reviews(
        [left, right],
        [],
        catalogue=load_alias_catalogue(FIXTURE_ROOT / "organization-aliases.yml"),
    )
    assert len(proposals) == 1
    assert proposals[0].similarity_score == pytest.approx(2 / 3, rel=0.01)
    assert len(resolve_organizations([left, right], [])) == 2


def test_candidate_requires_exact_entity_date_and_different_sources(notification_factory) -> None:
    left = notification_factory(source_id="washington", record_id="wa:1")
    right = notification_factory(source_id="california", record_id="ca:1")
    weak = notification_factory(
        source_id="california",
        record_id="ca:2",
        observed_date=date(2025, 12, 2),
    )
    same_source = notification_factory(source_id="washington", record_id="wa:2")
    candidates = generate_candidates([left, right, weak])
    assert len(candidates) == 1
    assert candidates[0].record_ids == ["ca:1", "wa:1"]
    assert "not proof" in candidates[0].limitations[0]
    assert generate_candidates([left, same_source]) == []


def test_reviewed_relationships_publish_confirmations_and_suppress_rejections(
    tmp_path: Path,
    notification_factory,
) -> None:
    left = notification_factory(source_id="washington", record_id="wa:1")
    right = notification_factory(source_id="california", record_id="ca:1")
    candidate = generate_candidates([left, right])[0]
    decision_id = relationship_decision_id(candidate.candidate_id, candidate.record_ids)
    path = tmp_path / "relationships.yml"
    path.write_text(
        f"""
schema_version: "1.0"
decisions:
  - decision_id: "{decision_id}"
    candidate_id: "{candidate.candidate_id}"
    status: confirmed_related
    record_ids: [ca:1, wa:1]
    evidence: ["Exact synthetic source labels and occurrence date."]
    reviewed_on: 2026-01-01
    review_note: "Synthetic confirmation for deterministic testing."
""".lstrip(),
        encoding="utf-8",
    )
    published, decisions = apply_relationship_decisions(
        [candidate],
        catalogue=load_relationship_catalogue(path),
    )
    assert published[0].reviewed is True
    assert published[0].review_status == "confirmed_related"
    assert published[0].relationship_class == "likely_same_publicly_reported_event"
    assert decisions[0].decision_id == decision_id

    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "status: confirmed_related",
            "status: rejected",
        ),
        encoding="utf-8",
    )
    suppressed, decisions = apply_relationship_decisions(
        [generate_candidates([left, right])[0]],
        catalogue=load_relationship_catalogue(path),
    )
    assert suppressed == []
    assert decisions[0].status == "rejected"


@given(st.lists(st.integers(), max_size=30))
def test_deterministic_ordering(values: list[int]) -> None:
    assert canonical_json_bytes(sorted(values)) == canonical_json_bytes(sorted(reversed(values)))


def test_compare_records_is_deterministic_and_partial_snapshots_do_not_remove(
    notification_factory,
) -> None:
    observed = datetime(2026, 1, 2, tzinfo=UTC)
    old = notification_factory(record_id="source:1")
    changed = old.model_copy(deep=True)
    changed.industry = "Healthcare"
    events = compare_records(
        {"source:1": old},
        {"source:1": changed},
        source_id="washington",
        current_snapshot="b" * 64,
        previous_snapshot="a" * 64,
        observed_at=observed,
        completeness=Completeness.COMPLETE,
    )
    repeated = compare_records(
        {"source:1": old},
        {"source:1": changed},
        source_id="washington",
        current_snapshot="b" * 64,
        previous_snapshot="a" * 64,
        observed_at=observed,
        completeness=Completeness.COMPLETE,
    )
    assert [event.event_id for event in events] == [event.event_id for event in repeated]
    assert events[0].event_type == "source_record_corrected"
    partial = compare_records(
        {"source:1": old},
        {},
        source_id="washington",
        current_snapshot="c" * 64,
        previous_snapshot="a" * 64,
        observed_at=observed,
        completeness=Completeness.ROLLING_WINDOW,
    )
    assert partial == []
    complete = compare_records(
        {"source:1": old},
        {},
        source_id="washington",
        current_snapshot="c" * 64,
        previous_snapshot="a" * 64,
        observed_at=observed,
        completeness=Completeness.COMPLETE,
    )
    assert complete[0].event_type == "source_status_changed"


def test_first_observation_event_excludes_complete_record(notification_factory) -> None:
    record = notification_factory(record_id="source:new")
    event = compare_records(
        {},
        {"source:new": record},
        source_id="washington",
        current_snapshot="b" * 64,
        previous_snapshot=None,
        observed_at=datetime(2026, 1, 2, tzinfo=UTC),
        completeness=Completeness.COMPLETE,
    )[0]
    assert event.after_value == {
        "source_record_id": "source:new",
        "source_checksum": "a" * 64,
    }
