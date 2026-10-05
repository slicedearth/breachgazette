"""Generate synthetic routing proof assets using the production Python builder."""

from datetime import UTC, date, datetime
from pathlib import Path

from breachgazette.contracts import NormalizedNotification
from breachgazette.publish import builder
from breachgazette.publish.builder import _build_search_assets, _detail_record_ids, _latest_date
from breachgazette.publish.search import normalize_search
from breachgazette.utils import atomic_write_json, normalize_organization_name, read_json

root = Path(__file__).resolve().parents[1]
template = read_json(root / "tests/fixtures/site/notifications.json")[0]
names = [
    "Straße Example",
    "İstanbul Example",
    "CAFÉ Example",
    "Cafe\u0301 Example",
    "𐐀 Example",
    "Whitespace\u2003Example",
    "Example One",
    "Example Two",
    "Example Three",
    "Example Four",
    "Example Five",
]
counts = [None, 0, 1, 499, 500, 999, 1000, 9999, 10000, 99999, 100000]
records = []
for index, (name, count) in enumerate(zip(names, counts, strict=True)):
    item = {
        **template,
        "source_id": "fixture",
        "source_record_id": f"fixture-golden-{index}",
        "record_type": "notification",
        "source_checksum": "a" * 64,
        "parser_version": "1.0",
        "normalization_version": "1.0",
        "named_entity": {
            **template["named_entity"],
            "source_name": name,
            "normalized_name": normalize_organization_name(name),
            "origin": "source_observed",
        },
        "affected_population": {
            "count": count,
            "scope": "Synthetic population",
            "estimated": False,
            "origin": "source_observed",
            "state": "present" if count is not None else "null",
        },
        "dates": [
            {
                "meaning": "occurrence_start",
                "normalized_date": "2025-12-20",
                "origin": "source_observed",
                "state": "present",
            },
            {
                "meaning": "public_notification_date",
                "normalized_date": "2026-01-10",
                "origin": "source_observed",
                "state": "present",
            },
        ],
    }
    records.append(NormalizedNotification.model_validate(item))
builder.SEARCH_PARTITION_SIZE = 1  # Exercise cold and out-of-order partitions in this fixture only.
manifest, partitions = _build_search_assets(
    records, detail_ids=set(), generated_at=datetime(2026, 1, 15, tzinfo=UTC)
)
queries = ["STRASSE", "İSTANBUL", "CAFÉ", "CAFE\u0301", "𐐨", "Whitespace\u0085Example"]
aged_records = [records[0].model_copy(deep=True)]
for index in range(251):
    newer = records[0].model_copy(deep=True)
    newer.source_record_id = f"fixture-newer-{index}"
    newer.dates[-1].normalized_date = date(2026, 2, 1)
    aged_records.append(newer)
builder.SEARCH_PARTITION_SIZE = 250
aged_records.sort(key=lambda item: (_latest_date(item), item.source_record_id), reverse=True)
aged_manifest, aged_partitions = _build_search_assets(
    aged_records,
    detail_ids=_detail_record_ids(aged_records),
    generated_at=datetime(2026, 2, 2, tzinfo=UTC),
)
atomic_write_json(
    root / "tests/fixtures/search-routing.json",
    {
        "dataset_class": "test_fixture",
        "manifest": manifest,
        "partitions": dict(partitions),
        "aged": {"manifest": aged_manifest, "partitions": dict(aged_partitions)},
        "cases": [
            {
                "query": value,
                "normalized": normalize_search(value),
                "expected_ids": [
                    record.source_record_id
                    for record in records
                    if all(
                        token in normalize_search(record.named_entity.source_name)
                        for token in normalize_search(value).split(" ")
                    )
                ],
            }
            for value in queries
        ],
    },
)
