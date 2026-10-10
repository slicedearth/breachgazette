"""Single-writer staged state generations with rollback on promotion failure."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from breachgazette.state.recovery import (
    cleanup_path,
    clear_journal,
    prepare_journal,
    promotion_pending,
    sync_directory,
)


@contextmanager
def state_lock(root: Path, *, allow_recovery: bool = False) -> Iterator[None]:
    if root.is_symlink():
        raise ValueError("state root must not be a symbolic link")
    try:
        import fcntl
    except ImportError as exc:
        raise RuntimeError("state updates require POSIX filesystem locking") from exc
    resolved = root.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise ValueError("private-state root is too broad")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        resolved.with_name(f".{resolved.name}.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another writer owns this private-state root") from exc
        if promotion_pending(resolved) and not allow_recovery:
            raise ValueError("an interrupted promotion requires recover-state before writing")
        yield
    finally:
        os.close(descriptor)


def copy_candidate(root: Path) -> Path:
    candidate = Path(tempfile.mkdtemp(prefix=f".{root.name}-candidate-", dir=root.parent))
    try:
        if root.exists():
            shutil.copytree(
                root, candidate, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git")
            )
        return candidate
    except BaseException:
        shutil.rmtree(candidate, ignore_errors=True)
        raise


def promote_candidate(root: Path, candidate: Path) -> None:
    backup = root.with_name(f".{root.name}-previous")
    if backup.exists() or backup.is_symlink():
        raise ValueError("a previous update backup already exists; review it before retrying")
    prepare_journal(root, candidate)
    existed = root.exists()
    try:
        if existed:
            root.rename(backup)
            sync_directory(root.parent)
        git_directory = backup / ".git"
        if existed and git_directory.exists():
            git_directory.rename(candidate / ".git")
            sync_directory(backup)
            sync_directory(candidate)
        candidate.rename(root)
        sync_directory(root.parent)
    except BaseException:
        if root.exists() and not candidate.exists():
            root.rename(candidate)
        candidate_git = candidate / ".git"
        if existed and candidate_git.exists() and not (backup / ".git").exists():
            candidate_git.rename(backup / ".git")
            sync_directory(candidate)
            sync_directory(backup)
        if existed and backup.exists():
            backup.rename(root)
        sync_directory(root.parent)
        clear_journal(root)
        raise
    if existed:
        # Retire the old tree atomically before any destructive cleanup. A partial
        # cleanup is not an ambiguous rollback generation in the pending journal.
        cleanup = cleanup_path(root, candidate.name)
        backup.rename(cleanup)
        sync_directory(root.parent)
        shutil.rmtree(cleanup, ignore_errors=True)
        if cleanup.exists() or cleanup.is_symlink():
            return
    clear_journal(root)


def discard_candidate(root: Path, candidate: Path) -> None:
    """Keep interrupted generations available for explicit recovery."""
    if not promotion_pending(root):
        shutil.rmtree(candidate, ignore_errors=True)
