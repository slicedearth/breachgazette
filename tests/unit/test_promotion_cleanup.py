from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from breachgazette.state.recovery import (
    cleanup_path,
    journal_path,
    prepare_journal,
    recover_generation,
)
from breachgazette.state.transaction import copy_candidate, promote_candidate, state_lock

CLEANUP_CHILD = """
import os
import shutil
import sys
from pathlib import Path
from breachgazette.state.transaction import promote_candidate, state_lock
root, candidate = Path(sys.argv[1]), Path(sys.argv[2])
boundary, termination = sys.argv[3], int(sys.argv[4])
real_rmtree, real_unlink, real_rmdir = shutil.rmtree, os.unlink, os.rmdir
active = None
unlinks = 0
def unlink(path, *args, **kwargs):
    global unlinks
    result = real_unlink(path, *args, **kwargs)
    if active is not None:
        unlinks += 1
        if boundary == "first_unlink" and unlinks == 1:
            os.kill(os.getpid(), termination)
    return result
def rmdir(path, *args, **kwargs):
    final = active is not None and os.fspath(path) == os.fspath(active)
    if final and boundary == "before_final_rmdir":
        os.kill(os.getpid(), termination)
    result = real_rmdir(path, *args, **kwargs)
    if active is not None and (
        (not final and boundary == "intermediate_rmdir") or
        (final and boundary == "after_final_rmdir")
    ):
        os.kill(os.getpid(), termination)
    return result
def rmtree(path, *args, **kwargs):
    global active
    active = Path(path)
    try:
        return real_rmtree(path, *args, **kwargs)
    finally:
        active = None
os.unlink, os.rmdir, shutil.rmtree = unlink, rmdir, rmtree
with state_lock(root):
    promote_candidate(root, candidate)
"""


RECOVERY_CHILD = """
import os
import sys
from pathlib import Path
from breachgazette.state import recovery
root, boundary, termination = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
real_rename, real_clear = Path.rename, recovery.clear_journal
renames = 0
def rename(self, target):
    global renames
    result = real_rename(self, target)
    renames += 1
    if boundary == f"rename:{renames}":
        os.kill(os.getpid(), termination)
    return result
def clear(root):
    if boundary == "before_clear":
        os.kill(os.getpid(), termination)
    real_clear(root)
    if boundary == "after_clear":
        os.kill(os.getpid(), termination)
Path.rename, recovery.clear_journal = rename, clear
recovery.recover_generation(root, apply=True)
"""


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _synthetic_generation(tmp_path: Path) -> tuple[Path, Path, dict[str, bytes], tuple[int, int]]:
    root = tmp_path / "synthetic-fixture-state"
    for name, content in {
        "state/records.json": '{"dataset_class":"test_fixture","value":"old"}\n',
        "events/nested/first.jsonl": '{"event":"synthetic-first"}\n',
        "events/second.jsonl": '{"event":"synthetic-second"}\n',
        "metadata/source.json": '{"source":"synthetic"}\n',
        ".git/marker": "synthetic repository metadata\n",
    }.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    metadata = (root / ".git").stat()
    candidate = copy_candidate(root)
    (candidate / "state/records.json").write_text(
        '{"dataset_class":"test_fixture","value":"new"}\n'
    )
    (candidate / "events/second.jsonl").write_bytes(
        (root / "events/second.jsonl").read_bytes() + b'{"event":"synthetic-third"}\n'
    )
    expected = {**_files(candidate), ".git/marker": (root / ".git/marker").read_bytes()}
    return root, candidate, expected, (metadata.st_dev, metadata.st_ino)


def _interrupt_cleanup(root: Path, candidate: Path, boundary: str, termination: int) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            CLEANUP_CHILD,
            str(root),
            str(candidate),
            boundary,
            str(termination),
        ],
        cwd=root.parent,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == -termination, result.stderr.decode()


def _assert_settled(root: Path, expected: dict[str, bytes], metadata: tuple[int, int]) -> None:
    assert _files(root) == expected
    info = (root / ".git").stat()
    assert (info.st_dev, info.st_ino) == metadata
    assert not journal_path(root).exists()
    assert not root.with_name(f".{root.name}-previous").exists()
    assert recover_generation(root, apply=True) == {"status": "clean", "applied": False}
    with state_lock(root):
        assert _files(root) == expected


@pytest.mark.skipif(os.name != "posix", reason="generation writers require POSIX locks")
@pytest.mark.parametrize(
    "boundary", ["first_unlink", "intermediate_rmdir", "before_final_rmdir", "after_final_rmdir"]
)
@pytest.mark.parametrize("termination", [signal.SIGKILL, signal.SIGTERM])
def test_cleanup_interruptions_retain_committed_state_and_allow_explicit_recovery(
    tmp_path, boundary, termination
):
    root, candidate, expected, metadata = _synthetic_generation(tmp_path)
    _interrupt_cleanup(root, candidate, boundary, termination)
    assert _files(root) == expected and not candidate.exists()
    with pytest.raises(ValueError, match="recover-state"), state_lock(root):
        pytest.fail("pending cleanup allowed another writer")
    before = _files(tmp_path)
    inspection = recover_generation(root)
    assert inspection["applied"] is False
    assert _files(tmp_path) == before
    applied = recover_generation(root, apply=True)
    assert applied["applied"] is True
    if boundary == "after_final_rmdir":
        assert inspection["status"] == "complete"
        assert applied["retained_cleanup"] is None
    else:
        assert inspection["status"] == "cleanup_pending"
        cleanup = tmp_path / applied["retained_cleanup"]
        assert cleanup.is_dir()
        assert _files(cleanup) == {
            name.removeprefix(f"{cleanup.name}/"): content
            for name, content in before.items()
            if name.startswith(f"{cleanup.name}/")
        }
        assert applied["retained_previous"] is None
    _assert_settled(root, expected, metadata)


def test_partial_cleanup_error_preserves_committed_bytes_and_can_be_settled(tmp_path, monkeypatch):
    root, candidate, expected, metadata = _synthetic_generation(tmp_path)
    original_unlink = os.unlink
    unlinks = 0

    def unlink(path, *args, **kwargs):
        nonlocal unlinks
        if unlinks:
            raise PermissionError("synthetic cleanup error")
        unlinks += 1
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as failure, state_lock(root):
        failure.setattr(os, "unlink", unlink)
        promote_candidate(root, candidate)
    assert unlinks == 1 and _files(root) == expected
    before = _files(tmp_path)
    assert recover_generation(root)["status"] == "cleanup_pending"
    assert _files(tmp_path) == before
    result = recover_generation(root, apply=True)
    assert (tmp_path / result["retained_cleanup"]).is_dir()
    _assert_settled(root, expected, metadata)


@pytest.mark.parametrize(
    "tamper",
    [
        "current",
        "candidate",
        "duplicate_metadata",
        "moved_metadata",
        "replaced_metadata",
        "symlink",
        "cleanup_symlink",
        "previous",
        "cleanup_path",
        "missing_cleanup",
        "legacy_cleanup",
        "unsupported_schema",
        "oversized_journal",
        "special_file",
    ],
)
def test_cleanup_recovery_rejects_changed_authority_or_unsafe_remnants(tmp_path, tamper):
    root, candidate, _, _ = _synthetic_generation(tmp_path)
    _interrupt_cleanup(root, candidate, "first_unlink", signal.SIGKILL)
    path = journal_path(root)
    payload = json.loads(path.read_text())
    cleanup = tmp_path / payload["cleanup"]
    if tamper == "current":
        (root / "state/records.json").write_text("changed")
    elif tamper == "candidate":
        candidate.mkdir()
        (candidate / "value").write_text("changed candidate")
    elif tamper == "duplicate_metadata":
        (cleanup / ".git").mkdir()
    elif tamper == "moved_metadata":
        (root / ".git").rename(cleanup / ".git")
    elif tamper == "replaced_metadata":
        (root / ".git").rename(tmp_path / "other-metadata")
        (root / ".git").mkdir()
    elif tamper == "symlink":
        (cleanup / "link").symlink_to(root / "state/records.json")
    elif tamper == "cleanup_symlink":
        other = tmp_path / "other-remnants"
        cleanup.rename(other)
        cleanup.symlink_to(other, target_is_directory=True)
    elif tamper == "previous":
        root.with_name(f".{root.name}-previous").mkdir()
    elif tamper == "cleanup_path":
        payload["cleanup"] = "../outside"
        path.write_text(json.dumps(payload))
    elif tamper == "missing_cleanup":
        del payload["cleanup"]
        path.write_text(json.dumps(payload))
    elif tamper == "legacy_cleanup":
        payload["schema_version"] = "1.0"
        path.write_text(json.dumps(payload))
    elif tamper == "unsupported_schema":
        payload["schema_version"] = "99.0"
        path.write_text(json.dumps(payload))
    elif tamper == "oversized_journal":
        path.write_text(" " * 4097)
    else:
        os.mkfifo(cleanup / "special")
    for apply in (False, True):
        with pytest.raises(ValueError):
            recover_generation(root, apply=apply)
    assert path.exists()
    with pytest.raises(ValueError, match="recover-state"), state_lock(root):
        pytest.fail("unsafe cleanup was accepted")


@pytest.mark.parametrize("termination", [signal.SIGKILL, signal.SIGTERM])
@pytest.mark.parametrize(
    ("phase", "boundary"),
    [(1, "rename:1"), (2, "rename:1"), (2, "rename:2"), (3, "rename:1")],
)
def test_recovery_rename_interruptions_remain_restartable(tmp_path, phase, boundary, termination):
    root, candidate, committed, metadata = _synthetic_generation(tmp_path)
    original = _files(root)
    prepare_journal(root, candidate)
    previous = root.with_name(f".{root.name}-previous")
    root.rename(previous)
    if phase >= 2:
        (previous / ".git").rename(candidate / ".git")
    if phase == 3:
        candidate.rename(root)
    result = subprocess.run(
        [sys.executable, "-c", RECOVERY_CHILD, str(root), boundary, str(termination)],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == -termination, result.stderr.decode()
    assert journal_path(root).exists()
    before = _files(tmp_path)
    recover_generation(root)
    assert _files(tmp_path) == before
    recovered = recover_generation(root, apply=True)
    if phase == 3:
        assert _files(tmp_path / recovered["retained_cleanup"]) == {
            name: content for name, content in original.items() if not name.startswith(".git/")
        }
    else:
        assert candidate.is_dir()
        assert _files(candidate) == {
            name: content for name, content in committed.items() if not name.startswith(".git/")
        }
    _assert_settled(root, committed if phase == 3 else original, metadata)


@pytest.mark.parametrize("termination", [signal.SIGKILL, signal.SIGTERM])
@pytest.mark.parametrize("boundary", ["before_clear", "after_clear"])
def test_recovery_journal_settlement_interruptions_keep_cleanup_remnants(
    tmp_path, boundary, termination
):
    root, candidate, expected, metadata = _synthetic_generation(tmp_path)
    _interrupt_cleanup(root, candidate, "first_unlink", signal.SIGKILL)
    cleanup = cleanup_path(root, candidate.name)
    remnants = _files(cleanup)
    result = subprocess.run(
        [sys.executable, "-c", RECOVERY_CHILD, str(root), boundary, str(termination)],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == -termination, result.stderr.decode()
    assert journal_path(root).exists() == (boundary == "before_clear")
    before = _files(tmp_path)
    recover_generation(root)
    assert _files(tmp_path) == before
    recover_generation(root, apply=True)
    assert cleanup.is_dir() and _files(cleanup) == remnants
    _assert_settled(root, expected, metadata)


def test_cleanup_retirement_is_journalled_and_synced_before_deletion(tmp_path, monkeypatch):
    from breachgazette.state import transaction

    root, candidate, expected, metadata = _synthetic_generation(tmp_path)
    previous = root.with_name(f".{root.name}-previous")
    cleanup = cleanup_path(root, candidate.name)
    real_rename, real_sync, real_rmtree = (
        Path.rename,
        transaction.sync_directory,
        transaction.shutil.rmtree,
    )
    boundaries = []

    def rename(self, target):
        result = real_rename(self, target)
        if self == previous:
            assert Path(target) == cleanup
            boundaries.append("retired")
        return result

    def sync(path):
        real_sync(path)
        if boundaries and path == root.parent:
            boundaries.append("synced")

    def rmtree(path, **kwargs):
        assert path == cleanup and boundaries == ["retired", "synced"]
        assert json.loads(journal_path(root).read_text())["cleanup"] == cleanup.name
        assert _files(root) == expected and not previous.exists() and not candidate.exists()
        return real_rmtree(path, **kwargs)

    with monkeypatch.context() as checks, state_lock(root):
        checks.setattr(Path, "rename", rename)
        checks.setattr(transaction, "sync_directory", sync)
        checks.setattr(transaction.shutil, "rmtree", rmtree)
        promote_candidate(root, candidate)
    _assert_settled(root, expected, metadata)


@pytest.mark.parametrize("boundary", ["retire", "delete"])
def test_cleanup_exception_does_not_roll_back_committed_state(tmp_path, monkeypatch, boundary):
    from breachgazette.state import transaction

    root, candidate, expected, metadata = _synthetic_generation(tmp_path)
    real_rename = Path.rename

    def rename(self, target):
        if self == root.with_name(f".{root.name}-previous"):
            raise OSError("synthetic retirement failure")
        return real_rename(self, target)

    def rmtree(path, **kwargs):
        next(item for item in path.rglob("*") if item.is_file()).unlink()
        raise OSError("synthetic deletion failure")

    with monkeypatch.context() as failure, state_lock(root):
        if boundary == "retire":
            failure.setattr(Path, "rename", rename)
        else:
            failure.setattr(transaction.shutil, "rmtree", rmtree)
        with pytest.raises(OSError, match="synthetic"):
            promote_candidate(root, candidate)
    assert _files(root) == expected
    before = _files(tmp_path)
    assert recover_generation(root)["status"] == (
        "complete" if boundary == "retire" else "cleanup_pending"
    )
    assert _files(tmp_path) == before
    result = recover_generation(root, apply=True)
    assert (tmp_path / result["retained_cleanup"]).is_dir()
    _assert_settled(root, expected, metadata)


@pytest.mark.parametrize("symlink", [False, True])
def test_journal_refuses_an_existing_cleanup_destination(tmp_path, symlink):
    root, candidate, _, _ = _synthetic_generation(tmp_path)
    cleanup = cleanup_path(root, candidate.name)
    if symlink:
        cleanup.symlink_to(tmp_path / "absent")
    else:
        cleanup.mkdir()
    with pytest.raises(ValueError, match="cleanup destination"):
        prepare_journal(root, candidate)
    assert not journal_path(root).exists()


@pytest.mark.parametrize("existing", [False, True])
def test_cleanup_cannot_be_used_to_accept_an_uncommitted_generation(tmp_path, existing):
    root = tmp_path / "fixture-state"
    if existing:
        root.mkdir()
        (root / "value").write_text("old")
    candidate = copy_candidate(root)
    (candidate / "value").write_text("new")
    prepare_journal(root, candidate)
    cleanup_path(root, candidate.name).mkdir()
    for apply in (False, True):
        with pytest.raises(ValueError, match="ambiguous"):
            recover_generation(root, apply=apply)
    assert root.exists() == existing and candidate.is_dir()


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("schema", ["1.0", "1.1"])
def test_previous_tree_verification_stays_exact_for_both_journal_versions(
    tmp_path, partial, schema
):
    root, candidate, expected, metadata = _synthetic_generation(tmp_path)
    original = _files(root)
    with state_lock(root):
        prepare_journal(root, candidate)
    path = journal_path(root)
    payload = json.loads(path.read_text())
    payload["schema_version"] = schema
    if schema == "1.0":
        del payload["cleanup"]
    path.write_text(json.dumps(payload))
    previous = root.with_name(f".{root.name}-previous")
    root.rename(previous)
    (previous / ".git").rename(candidate / ".git")
    candidate.rename(root)
    if partial:
        (previous / "state/records.json").unlink()
        for apply in (False, True):
            with pytest.raises(ValueError, match="previous generation changed"):
                recover_generation(root, apply=apply)
        assert path.exists() and _files(root) == expected
    else:
        before = _files(tmp_path)
        assert recover_generation(root)["status"] == "complete"
        assert _files(tmp_path) == before
        result = recover_generation(root, apply=True)
        retained = result["retained_previous" if schema == "1.0" else "retained_cleanup"]
        assert result["retained_cleanup" if schema == "1.0" else "retained_previous"] is None
        assert _files(tmp_path / retained) == {
            name: content for name, content in original.items() if not name.startswith(".git/")
        }
        _assert_settled(root, expected, metadata)


def test_cleanup_recovery_cli_inspects_before_applying(tmp_path):
    from typer.testing import CliRunner

    from breachgazette.cli import app

    root, candidate, expected, metadata = _synthetic_generation(tmp_path)
    _interrupt_cleanup(root, candidate, "first_unlink", signal.SIGKILL)
    arguments = ["recover-state", "--data-root", str(root), "--json"]
    before = _files(tmp_path)
    inspection = CliRunner().invoke(app, arguments)
    assert inspection.exit_code == 0, inspection.output
    assert json.loads(inspection.stdout)["status"] == "cleanup_pending"
    assert _files(tmp_path) == before
    applied = CliRunner().invoke(app, [*arguments, "--apply"])
    assert applied.exit_code == 0, applied.output
    result = json.loads(applied.stdout)
    assert result["applied"] is True and (tmp_path / result["retained_cleanup"]).is_dir()
    _assert_settled(root, expected, metadata)


def test_pending_promotion_preserves_candidate_and_suppresses_failed_checkpoint(
    tmp_path, monkeypatch
):
    from breachgazette import pipeline

    root = tmp_path / "synthetic-fixture-state"
    root.mkdir()
    (root / "original").write_text("synthetic original state")
    original = _files(root)

    def update(source_id, *, data_root):
        (data_root / "candidate").write_text("synthetic candidate state")
        return {"source_id": source_id}

    def interrupted(root, candidate):
        prepare_journal(root, candidate)
        raise OSError("synthetic interruption with pending journal")

    monkeypatch.setattr(pipeline, "_update_source_generation", update)
    monkeypatch.setattr(pipeline, "promote_candidate", interrupted)
    with pytest.raises(OSError, match="pending journal"):
        pipeline.update_source("washington", data_root=root)
    assert _files(root) == original
    pending = json.loads(journal_path(root).read_text())
    candidate = tmp_path / pending["candidate"]
    assert (candidate / "candidate").read_text() == "synthetic candidate state"
    assert not (root / "checkpoints").exists()
    assert recover_generation(root, apply=True)["status"] == "original"
    assert _files(root) == original and candidate.is_dir()
    with state_lock(root):
        assert _files(root) == original
