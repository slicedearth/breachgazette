from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from breachgazette.contracts import SourceHealthEntry, SourceHealthReport
from breachgazette.operations import run_update_cycle, source_health_summary
from breachgazette.retention import (
    RetentionPolicy,
    compact_state,
    create_state_backup,
    restore_state_backup,
    state_inventory,
)
from breachgazette.utils import atomic_write_json, sha256_hex


def _policy(*, history: int = 53) -> RetentionPolicy:
    return RetentionPolicy(
        schema_version="1.0",
        managed_directories=(
            "checkpoints",
            "events",
            "manifests",
            "metadata",
            "reports",
            "reviews",
            "state",
        ),
        maximum_history_reports=history,
        maximum_state_bytes=10_000_000,
        maximum_archive_bytes=10_000_000,
    )


def _tree_checksums(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_hex(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _health(*, passed: bool = True) -> SourceHealthReport:
    observed = datetime(2026, 7, 23, tzinfo=UTC)
    return SourceHealthReport(
        generated_at=observed,
        dataset_class="real_source_data",
        passed=passed,
        schedule_utc="23 17 * * 1",
        sources=[
            SourceHealthEntry(
                source_id="washington",
                status="healthy" if passed else "failed_update",
                record_count=4,
                minimum_records=1,
                completeness="complete",
                snapshot_checksum="a" * 64,
                snapshot_age_hours=1,
                stale_after_hours=240,
                latest_attempted_update=observed,
                last_successful_update=observed,
                checkpoint_status="complete" if passed else "failed",
                reasons=["private raw value that must not reach summaries"],
            )
        ],
        limitations=["private raw value that must not reach summaries"],
    )


def test_update_cycle_failure_preserves_original_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private-state"
    atomic_write_json(
        root / "metadata" / "dataset-class.json",
        {"dataset_class": "real_source_data"},
    )
    atomic_write_json(root / "state" / "washington.json", [{"original": True}])
    before = _tree_checksums(root)

    def failing_update(*, data_root: Path, sources: list[str] | None) -> list[dict[str, object]]:
        del sources
        atomic_write_json(data_root / "state" / "washington.json", [{"changed": True}])
        raise RuntimeError("injected source failure")

    monkeypatch.setattr(
        "breachgazette.operations.build_source_health_report",
        lambda **_: _health(),
    )
    with pytest.raises(RuntimeError, match="injected"):
        run_update_cycle(
            data_root=root,
            updater=failing_update,
            builder=lambda **_: {"quality_passed": True},
            auditor=lambda _: {"passed": True},
        )
    assert _tree_checksums(root) == before
    assert not list(tmp_path.glob(".private-state-candidate-*"))


def test_update_cycle_promotes_verified_candidate_and_preserves_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private-state"
    atomic_write_json(
        root / "metadata" / "dataset-class.json",
        {"dataset_class": "real_source_data"},
    )
    atomic_write_json(root / "state" / "washington.json", [{"original": True}])
    (root / ".git").mkdir()
    (root / ".git" / "marker").write_text("repository metadata", encoding="utf-8")

    def successful_update(
        *,
        data_root: Path,
        sources: list[str] | None,
    ) -> list[dict[str, object]]:
        del sources
        atomic_write_json(data_root / "state" / "washington.json", [{"verified": True}])
        return [{"source_id": "washington"}]

    def successful_build(*, data_root: Path, output: Path) -> dict[str, object]:
        assert (data_root / "state" / "washington.json").is_file()
        output.mkdir(parents=True, exist_ok=True)
        (output / "index.html").write_text("safe", encoding="utf-8")
        return {"quality_passed": True}

    monkeypatch.setattr(
        "breachgazette.operations.build_source_health_report",
        lambda **_: _health(),
    )
    result = run_update_cycle(
        data_root=root,
        promote=True,
        updater=successful_update,
        builder=successful_build,
        auditor=lambda _: {"passed": True},
    )
    assert result["promoted"] is True
    assert '"verified":true' in (root / "state" / "washington.json").read_text()
    assert (root / ".git" / "marker").read_text(encoding="utf-8") == "repository metadata"
    assert (root / "reports" / "source-health.json").is_file()


def test_retention_keeps_53_weeks_and_backup_restore_round_trips(tmp_path: Path) -> None:
    root = tmp_path / "private-state"
    for week in range(60):
        atomic_write_json(
            root / "reports" / "history" / f"source-health-2025{week:02d}.json",
            {"week": week},
        )
    atomic_write_json(root / "events" / "notification-events.json", [{"event": "kept"}])
    atomic_write_json(root / "state" / "washington.json", [{"record": "kept"}])
    before_events = (root / "events" / "notification-events.json").read_bytes()
    before_state = (root / "state" / "washington.json").read_bytes()

    preview = compact_state(root, policy=_policy())
    assert preview["applied"] is False
    assert len(preview["planned"]) == 7
    applied = compact_state(root, apply=True, policy=_policy())
    assert len(applied["removed"]) == 7
    assert len(list((root / "reports" / "history").glob("*.json"))) == 53
    assert (root / "events" / "notification-events.json").read_bytes() == before_events
    assert (root / "state" / "washington.json").read_bytes() == before_state

    archive = tmp_path / "state-backup.zip"
    backup = create_state_backup(root, archive, policy=_policy())
    assert backup["files"] == state_inventory(root, policy=_policy())["files"]
    with pytest.raises(ValueError, match="already exists"):
        create_state_backup(root, archive, policy=_policy())
    repeated = create_state_backup(
        root,
        tmp_path / "state-backup-repeat.zip",
        policy=_policy(),
    )
    assert repeated["checksum_sha256"] == backup["checksum_sha256"]
    restored = tmp_path / "restored-state"
    result = restore_state_backup(
        archive,
        restored,
        expected_sha256=backup["checksum_sha256"],
        policy=_policy(),
    )
    assert result["files"] == backup["files"]
    assert result["archive_checksum_sha256"] == backup["checksum_sha256"]
    assert _tree_checksums(restored) == _tree_checksums(root)


def test_restore_rejects_nonempty_destination_and_summary_is_sanitized(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-state"
    atomic_write_json(root / "state" / "washington.json", [{"record": "safe"}])
    archive = tmp_path / "state.zip"
    backup = create_state_backup(root, archive, policy=_policy())
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="absent or empty"):
        restore_state_backup(
            archive,
            destination,
            expected_sha256=backup["checksum_sha256"],
            policy=_policy(),
        )
    assert (destination / "keep.txt").read_text(encoding="utf-8") == "keep"

    report = tmp_path / "health.json"
    atomic_write_json(report, _health(passed=False))
    summary = source_health_summary(report)
    assert "washington" in summary
    assert "failed_update" in summary
    assert "private raw value" not in summary
    assert "2026-07-23" not in summary
    assert "a" * 64 not in summary


def test_restore_rejects_archive_checksum_mismatch_before_extracting(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-state"
    atomic_write_json(root / "state" / "washington.json", [{"record": "safe"}])
    archive = tmp_path / "state.zip"
    backup = create_state_backup(root, archive, policy=_policy())
    destination = tmp_path / "restored"
    tampered = bytearray(archive.read_bytes())
    tampered[len(tampered) // 2] ^= 1
    archive.write_bytes(tampered)

    with pytest.raises(ValueError, match="does not match"):
        restore_state_backup(
            archive,
            destination,
            expected_sha256=backup["checksum_sha256"],
            policy=_policy(),
        )
    assert not destination.exists()

    with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
        restore_state_backup(
            archive,
            destination,
            expected_sha256=backup["checksum_sha256"].upper(),
            policy=_policy(),
        )
    assert not destination.exists()


def test_backup_failure_leaves_no_partial_archive(tmp_path: Path) -> None:
    root = tmp_path / "private-state"
    atomic_write_json(root / "state" / "washington.json", [{}])
    output = tmp_path / "state.zip"
    policy = _policy().model_copy(update={"maximum_archive_bytes": 50})

    with pytest.raises(ValueError, match="archive size bound"):
        create_state_backup(root, output, policy=policy)
    assert not output.exists()
    assert not list(tmp_path.glob(".state.zip.*.tmp"))
