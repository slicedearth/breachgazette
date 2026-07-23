from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from breachgazette.clients.washington import MAIN_FIELDS, WashingtonAdapter, _parse_date
from breachgazette.compare import compare_records
from breachgazette.contracts.enums import Completeness
from breachgazette.relationships import generate_candidates


@given(st.dates())
def test_source_date_normalization_preserves_iso_dates(value) -> None:
    assert _parse_date(f"{value.isoformat()}T23:59:59.000") == value


@given(st.integers(min_value=0, max_value=10_000_000))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_relationship_blocking_never_groups_distinct_entities(
    notification_factory,
    suffix: int,
) -> None:
    left = notification_factory(
        source_id="washington",
        record_id=f"wa:{suffix}",
        name=f"Example Alpha {suffix}",
    )
    right = notification_factory(
        source_id="california",
        record_id=f"ca:{suffix}",
        name=f"Example Beta {suffix}",
    )
    assert generate_candidates([left, right]) == []


@given(st.integers(min_value=0, max_value=10_000_000))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_event_ids_are_stable_for_arbitrary_source_ids(
    notification_factory,
    suffix: int,
) -> None:
    record_id = f"source:{suffix}"
    record = notification_factory(record_id=record_id)
    arguments = {
        "previous": {},
        "current": {record_id: record},
        "source_id": "washington",
        "current_snapshot": "b" * 64,
        "previous_snapshot": None,
        "observed_at": datetime(2026, 1, 2, tzinfo=UTC),
        "completeness": Completeness.COMPLETE,
    }
    first = compare_records(**arguments)
    second = compare_records(**arguments)
    assert first[0].event_id == second[0].event_id
    assert len(first[0].event_id) == 64


class _PagedJsonClient:
    def __init__(self, count: int) -> None:
        self.count = count
        self.offsets: list[int] = []

    def get_json(self, url: str):
        query = parse_qs(urlparse(url).query)
        if query.get("$select") == ["count(*) as count"]:
            return [{"count": str(self.count)}], {}, url
        offset = int(query["$offset"][0])
        limit = int(query["$limit"][0])
        self.offsets.append(offset)
        stop = min(offset + limit, self.count)
        return [{"id": str(index)} for index in range(offset, stop)], {}, url


@given(st.integers(min_value=1, max_value=5_000))
def test_washington_pagination_is_bounded_and_reconciled(count: int) -> None:
    adapter = WashingtonAdapter()
    client = _PagedJsonClient(count)
    rows = adapter._fetch_rows(client, "fixed-dataset", MAIN_FIELDS)  # type: ignore[arg-type]
    assert len(rows) == count
    assert client.offsets == list(range(0, count, adapter.page_size))
