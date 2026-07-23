from __future__ import annotations

from datetime import UTC, date, datetime

from hypothesis import given
from hypothesis import strategies as st

from breachgazette.compare import compare_records
from breachgazette.contracts.enums import Completeness
from breachgazette.entities import resolve_organizations
from breachgazette.relationships import generate_candidates
from breachgazette.utils import canonical_json_bytes


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
