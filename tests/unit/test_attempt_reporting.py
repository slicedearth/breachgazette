from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from breachgazette.contracts import SourceHealthReport, SourceSnapshot, UpdateCheckpoint
from breachgazette.operations import attempt_summary, run_update_cycle
from breachgazette.state import PrivateStateStore
from breachgazette.utils import atomic_write_json, read_json


@pytest.mark.parametrize(
    "failure",
    ["retrieval", "health_validation", "publication_validation", "public_tree_validation", "none"],
)
def test_attempts_survive_failure_without_promoting_or_leaking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    root = tmp_path / "synthetic-state"
    atomic_write_json(root / "metadata/dataset-class.json", {"dataset_class": "real_source_data"})
    production_snapshot = SourceSnapshot(
        source_id="washington",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed_at=datetime(2026, 1, 1, tzinfo=UTC),
        revision="synthetic-prior",
        checksum_sha256="a" * 64,
        completeness="complete",
        records_discovered=1,
        records_accepted=1,
        records_rejected=0,
        bounded_limit=100,
        latest_attempted_update=datetime(2026, 1, 1, tzinfo=UTC),
    )
    PrivateStateStore(root).write_snapshot(production_snapshot)
    before = {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    report = tmp_path / "diagnostics/attempt.json"
    secret = "https://user:secret@private.example/raw"

    def update(*, data_root, sources):
        candidate_snapshot = production_snapshot.model_copy(deep=True)
        candidate_snapshot.completed_at = datetime.now(UTC)
        candidate_snapshot.records_accepted = candidate_snapshot.records_discovered = 2
        PrivateStateStore(data_root).write_snapshot(candidate_snapshot)
        PrivateStateStore(data_root).write_checkpoint(
            UpdateCheckpoint(
                source_id="washington",
                attempted_at=datetime.now(UTC),
                status="failed" if failure == "retrieval" else "complete",
                detail="Synthetic diagnostic.",
            )
        )
        if failure == "retrieval":
            raise RuntimeError(secret)
        return [{"source_id": "washington"}]

    def health(**_):
        if failure == "health_validation":
            raise RuntimeError(secret)
        return SourceHealthReport(
            generated_at=datetime.now(UTC),
            dataset_class="real_source_data",
            passed=True,
            schedule_utc="23 17 * * 1",
            sources=[],
            limitations=["Synthetic test only."],
        )

    def build(**_):
        if failure == "publication_validation":
            raise RuntimeError(secret)
        return {"quality_passed": True}

    def audit(_):
        if failure == "public_tree_validation":
            raise RuntimeError(secret)
        return {"passed": True}

    monkeypatch.setattr("breachgazette.operations.build_source_health_report", health)
    arguments = dict(
        data_root=root,
        sources=["washington", "california"],
        updater=update,
        builder=build,
        auditor=audit,
        attempt_report=report,
    )
    if failure == "none":
        assert run_update_cycle(**arguments)["promoted"] is False
    else:
        with pytest.raises(RuntimeError, match=r"private\.example"):
            run_update_cycle(**arguments)
    assert {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    payload = read_json(report)
    assert payload["phase"] == ("complete" if failure == "none" else failure)
    assert payload["sources"][0]["status"] == ("failed" if failure == "retrieval" else "complete")
    assert payload["sources"][1]["status"] == "not_attempted"
    assert payload["sources"][0]["production_record_count"] == 1
    assert payload["sources"][0]["last_successful_production_update"] == "2026-01-01T00:00:00Z"
    assert payload["sources"][0]["attempt_record_count"] == (None if failure == "retrieval" else 2)
    assert secret not in report.read_text()
    summary = attempt_summary(report)
    assert "private.example" not in summary and "secret" not in summary
    if failure != "none":
        failure = "none"
        assert run_update_cycle(**arguments)["promoted"] is False
        recovered = read_json(report)
        assert recovered["passed"] is True and recovered["phase"] == "complete"
        assert recovered["sources"][0]["status"] == "complete"
        assert (
            recovered["sources"][0]["last_successful_production_update"] == "2026-01-01T00:00:00Z"
        )
        assert {
            str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()
        } == before


def test_attempt_report_cannot_mutate_authoritative_state(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-state"
    root.mkdir()
    with pytest.raises(ValueError, match="outside"):
        run_update_cycle(data_root=root, attempt_report=root / "attempt.json")


def test_diagnostic_write_failure_still_discards_candidates(tmp_path, monkeypatch) -> None:
    root = tmp_path / "synthetic-state"
    root.mkdir()

    def update(**_):
        raise RuntimeError("synthetic retrieval failure")

    def fail_write(*_, **__):
        raise OSError("diagnostic storage unavailable")

    monkeypatch.setattr("breachgazette.operations.atomic_write_json", fail_write)
    with pytest.raises(OSError, match="diagnostic storage"):
        run_update_cycle(
            data_root=root,
            sources=["washington"],
            updater=update,
            attempt_report=tmp_path / "attempt.json",
        )
    assert not list(tmp_path.glob(".synthetic-state-candidate-*"))
    assert not list(tmp_path.glob(".breachgazette-publication-*"))
    assert list(root.iterdir()) == []
