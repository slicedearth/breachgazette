from __future__ import annotations

import os
import signal
import subprocess
import sys

import pytest

from breachgazette.state.transaction import copy_candidate, state_lock

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
    # Inspection/recovery starts only after reacquiring the same writer lock.
    with state_lock(root):
        if phase < 3:
            assert not root.exists() and candidate.is_dir()
            if (candidate / ".git").exists():
                assert not (previous / ".git").exists()
                (candidate / ".git").rename(previous / ".git")
            previous.rename(root)
            assert {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            } == original
            assert b'"value":"new"' in (candidate / "state/generation.json").read_bytes()
        else:
            # A completed new root is not overwritten merely because old state remains.
            assert root.is_dir() and not candidate.exists()
            assert b'"value":"new"' in (root / "state/generation.json").read_bytes()
            assert (root / ".git/marker").read_bytes() == original[".git/marker"]
