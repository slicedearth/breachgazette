from __future__ import annotations

import json
from pathlib import Path

import pytest

from breachgazette.pipeline import compare_summary, ingest_fixture, update_all, update_source
from breachgazette.state import PrivateStateStore


def test_fixture_ingestion_is_explicit_and_isolated(tmp_path: Path, notification_factory) -> None:
    record = notification_factory().model_dump(mode="json", exclude={"canonical_organization_id"})
    fixture = tmp_path / "notification-fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "dataset_class": "test_fixture",
                "source_id": "washington",
                "records": [record],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must include"):
        ingest_fixture(fixture, data_root=tmp_path / "state")
    root = tmp_path / "fixture-state"
    result = ingest_fixture(fixture, data_root=root)
    assert result == {
        "source_id": "washington",
        "records": 1,
        "dataset_class": "test_fixture",
    }
    assert PrivateStateStore(root).dataset_class() == "test_fixture"
    assert compare_summary(data_root=root) == {"events": 0, "event_types": {}}


def test_fixed_source_selection_rejects_unknown_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported source"):
        update_source("arbitrary", data_root=tmp_path)
    with pytest.raises(ValueError, match="unsupported sources"):
        update_all(data_root=tmp_path, sources=["arbitrary"])
