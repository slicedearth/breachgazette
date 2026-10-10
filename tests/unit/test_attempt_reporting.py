from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from breachgazette.attempts import append_attempt, history_target
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
    history = tmp_path / "private-attempt-history"
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
        attempt_history=history,
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
    retained = list(history.glob("attempt-*.json"))
    assert len(retained) == 1
    first_attempt = retained[0].read_bytes()
    assert secret.encode() not in first_attempt
    assert "limitations" not in read_json(retained[0])
    assert history.stat().st_mode & 0o077 == 0
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
        assert len(list(history.glob("attempt-*.json"))) == 2
        assert retained[0].read_bytes() == first_attempt


def test_private_history_retention_and_strict_fields(tmp_path, monkeypatch):
    from datetime import timedelta

    monkeypatch.setattr("breachgazette.attempts.MAX_ATTEMPTS", 2)
    history = tmp_path / "history"
    started = datetime(2026, 1, 1, tzinfo=UTC)
    report = {
        "schema_version": "1.0",
        "started_at": started,
        "completed_at": started,
        "passed": False,
        "promoted": False,
        "phase": "retrieval",
        "sources": [],
    }
    for day in range(3):
        value = {
            **report,
            "started_at": started + timedelta(days=day),
            "completed_at": started + timedelta(days=day),
        }
        append_attempt(history, value, source_ids={"washington"})
    entries = sorted(history.iterdir())
    assert len(entries) == 2 and "20260102" in entries[0].name
    assert all(entry.stat().st_mode & 0o077 == 0 for entry in entries)
    append_attempt(history, value, source_ids={"washington"})
    assert sorted(history.iterdir()) == entries
    with pytest.raises(ValueError):
        append_attempt(history, {**report, "exception": "private source data"}, source_ids=set())
    entries[0].write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        append_attempt(history, report, source_ids=set())


def test_history_rejects_state_overlap_symlinks_public_checkout_and_open_permissions(tmp_path):
    root = tmp_path / "fixture-state"
    root.mkdir()
    for path in (root, root / "history", tmp_path):
        with pytest.raises(ValueError, match="separate"):
            history_target(path, root)
    link = tmp_path / "link"
    link.symlink_to(root)
    with pytest.raises(ValueError, match="symbolic"):
        history_target(link, root)
    checkout = tmp_path / "checkout"
    (checkout / "src/breachgazette").mkdir(parents=True)
    (checkout / "pyproject.toml").touch()
    with pytest.raises(ValueError, match="source checkout"):
        history_target(checkout / "history", root)
    history = tmp_path / "open-history"
    history.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="owner-only"):
        append_attempt(
            history,
            {
                "schema_version": "1.0",
                "started_at": datetime.now(UTC),
                "completed_at": datetime.now(UTC),
                "passed": False,
                "promoted": False,
                "phase": "retrieval",
                "sources": [],
            },
            source_ids=set(),
        )


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
