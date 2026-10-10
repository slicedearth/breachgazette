from __future__ import annotations

import os
import signal
import subprocess
import sys

import pytest

from breachgazette.state.recovery import (
    journal_path,
    prepare_journal,
    recover_generation,
    tree_checksum,
)
from breachgazette.state.transaction import copy_candidate, discard_candidate, state_lock

CHILD = """
import os
import signal
import sys
from pathlib import Path
from breachgazette.state.transaction import promote_candidate, state_lock
root, candidate = Path(sys.argv[1]), Path(sys.argv[2])
phase, termination = int(sys.argv[3]), int(sys.argv[4])
original = Path.rename
calls = 0
def interrupted(self, target):
    global calls
    result = original(self, target)
    calls += 1
    if calls == phase:
        os.kill(os.getpid(), termination)
    return result
Path.rename = interrupted
with state_lock(root):
    promote_candidate(root, candidate)
"""


@pytest.mark.skipif(os.name != "posix", reason="generation writers require POSIX locks")
@pytest.mark.parametrize("phase", [1, 2, 3])
@pytest.mark.parametrize("termination", [signal.SIGKILL, signal.SIGTERM])
def test_interrupted_promotion_preserves_inspectable_generations_under_recovered_lock(
    tmp_path,
    phase,
    termination,
):
    root = tmp_path / "synthetic-fixture-state"
    (root / "state").mkdir(parents=True)
    (root / "state/generation.json").write_text('{"dataset_class":"test_fixture","value":"old"}')
    (root / ".git").mkdir()
    (root / ".git/marker").write_text("synthetic repository metadata")
    original = {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    candidate = copy_candidate(root)
    (candidate / "state/generation.json").write_text(
        '{"dataset_class":"test_fixture","value":"new"}'
    )
    result = subprocess.run(
        [sys.executable, "-c", CHILD, str(root), str(candidate), str(phase), str(termination)],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == -termination, result.stderr.decode()
    previous = root.with_name(f".{root.name}-previous")
    assert previous.is_dir()
    assert (previous / "state/generation.json").read_bytes() == original["state/generation.json"]
    with pytest.raises(ValueError, match="recover-state"), state_lock(root):
        pytest.fail("interrupted promotion allowed a new writer")
    before = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    inspection = recover_generation(root)
    assert inspection["status"] == ("restore_previous" if phase < 3 else "complete")
    assert inspection["applied"] is False
    assert {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before
    discard_candidate(root, candidate)
    assert candidate.exists() == (phase < 3)
    applied = recover_generation(root, apply=True)
    assert applied["applied"] is True and not journal_path(root).exists()
    if phase < 3:
        assert {
            str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        } == original
        assert b'"value":"new"' in (candidate / "state/generation.json").read_bytes()
    else:
        assert b'"value":"new"' in (root / "state/generation.json").read_bytes()
        assert (root / ".git/marker").read_bytes() == original[".git/marker"]
        retained = tmp_path / applied["retained_cleanup"]
        assert retained.is_dir() and not previous.exists()
    assert recover_generation(root, apply=True) == {"status": "clean", "applied": False}


@pytest.mark.parametrize("tamper", ["candidate", "previous", "metadata", "symlink"])
def test_recovery_rejects_changed_or_ambiguous_generations(tmp_path, tamper):
    root = tmp_path / "fixture-state"
    root.mkdir()
    (root / "value").write_text("old")
    (root / ".git").mkdir()
    candidate = copy_candidate(root)
    (candidate / "value").write_text("new")
    prepare_journal(root, candidate)
    previous = root.with_name(f".{root.name}-previous")
    root.rename(previous)
    if tamper == "candidate":
        (candidate / "value").write_text("different")
    elif tamper == "previous":
        (previous / "value").write_text("different")
    elif tamper == "metadata":
        (candidate / ".git").mkdir()
    else:
        (candidate / "link").symlink_to(previous / "value")
    with pytest.raises(ValueError):
        recover_generation(root, apply=True)
    assert not root.exists() and previous.exists() and candidate.exists()
    assert journal_path(root).exists()


@pytest.mark.parametrize("existing", [False, True])
def test_journal_before_first_rename_can_be_cleared_without_promoting(tmp_path, existing):
    root = tmp_path / "fixture-state"
    if existing:
        root.mkdir()
    candidate = copy_candidate(root)
    (candidate / "value").write_text("new")
    prepare_journal(root, candidate)
    result = recover_generation(root, apply=True)
    assert result["status"] == ("original" if existing else "unpromoted_initial")
    assert root.exists() == existing
    assert candidate.exists()


def test_recovery_rejects_unsafe_journal_and_unjournalled_previous(tmp_path):
    root = tmp_path / "fixture-state"
    root.mkdir()
    candidate = copy_candidate(root)
    prepare_journal(root, candidate)
    path = journal_path(root)
    path.write_text(path.read_text().replace(candidate.name, "../outside"))
    with pytest.raises(ValueError, match="candidate"):
        recover_generation(root, apply=True)
    path.unlink()
    root.rename(root.with_name(f".{root.name}-previous"))
    with pytest.raises(ValueError, match="unjournalled"):
        recover_generation(root, apply=True)


def test_generation_checksum_bounds_and_includes_unmanaged_files(tmp_path, monkeypatch):
    root = tmp_path / "fixture-state"
    root.mkdir()
    (root / "README").write_text("old")
    first = tree_checksum(root)
    (root / "README").write_text("new")
    assert tree_checksum(root) != first
    from types import SimpleNamespace

    monkeypatch.setattr(
        "breachgazette.state.recovery.load_retention_policy",
        lambda: SimpleNamespace(maximum_state_bytes=2),
    )
    with pytest.raises(ValueError, match="byte bound"):
        tree_checksum(root)
