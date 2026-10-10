"""Checksummed promotion journals and explicit, lock-protected recovery."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from breachgazette.retention import load_retention_policy
from breachgazette.utils import atomic_write_json, read_json, sha256_hex


class PromotionJournal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    candidate: str
    previous_checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    candidate_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    git_identity: tuple[int, int] | None


def journal_path(root: Path) -> Path:
    return root.with_name(f".{root.name}.promotion.json")


def promotion_pending(root: Path) -> bool:
    path = journal_path(root)
    return path.exists() or path.is_symlink()


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def tree_checksum(root: Path, *, sync: bool = False) -> str:
    """Hash every regular state entry, excluding only top-level repository metadata."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("generation must be a regular directory")
    entries: dict[str, str | None] = {}
    total = 0
    limit = load_retention_policy().maximum_state_bytes
    directories = [root]
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            if path == root / ".git":
                continue
            relative = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode
            if len(entries) >= 100_000:
                raise ValueError("generation exceeds its entry bound")
            if stat.S_ISDIR(mode):
                entries[relative] = None
                directories.append(path)
                pending.append(path)
            elif stat.S_ISREG(mode):
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        total += len(chunk)
                        if total > limit:
                            raise ValueError("generation exceeds its byte bound")
                        digest.update(chunk)
                    if sync:
                        os.fsync(handle.fileno())
                entries[relative] = digest.hexdigest()
            else:
                raise ValueError("generation contains a symbolic link or special file")
    if sync:
        for directory in reversed(directories):
            sync_directory(directory)
    return sha256_hex(entries)


def git_identity(root: Path) -> tuple[int, int] | None:
    path = root / ".git"
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError("repository metadata must be a regular file or directory")
    return info.st_dev, info.st_ino


def prepare_journal(root: Path, candidate: Path) -> None:
    if promotion_pending(root):
        raise ValueError("an interrupted promotion requires recovery before writing")
    if candidate.parent != root.parent or not re.fullmatch(
        rf"\.{re.escape(root.name)}-candidate-[a-z0-9_-]+", candidate.name
    ):
        raise ValueError("candidate must be a generated sibling directory")
    if git_identity(candidate) is not None:
        raise ValueError("candidate already contains repository metadata")
    journal = PromotionJournal(
        candidate=candidate.name,
        previous_checksum=tree_checksum(root, sync=True) if root.exists() else None,
        candidate_checksum=tree_checksum(candidate, sync=True),
        git_identity=git_identity(root),
    )
    atomic_write_json(journal_path(root), journal)
    sync_directory(root.parent)


def clear_journal(root: Path) -> None:
    journal_path(root).unlink()
    sync_directory(root.parent)


def recover_generation(root: Path, *, apply: bool = False) -> dict[str, Any]:
    from breachgazette.state.transaction import state_lock

    if root.is_symlink():
        raise ValueError("state root must not be a symbolic link")
    root = root.resolve()
    with state_lock(root, allow_recovery=True):
        path = journal_path(root)
        previous = root.with_name(f".{root.name}-previous")
        if not promotion_pending(root):
            if previous.exists() or previous.is_symlink():
                raise ValueError("unjournalled previous generation requires operator review")
            return {"status": "clean", "applied": False}
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise ValueError("promotion journal is not a bounded regular file")
        journal = PromotionJournal.model_validate(read_json(path))
        if journal.schema_version != "1.0" or not re.fullmatch(
            rf"\.{re.escape(root.name)}-candidate-[a-z0-9_-]+", journal.candidate
        ):
            raise ValueError("promotion journal has an unsupported schema or candidate")
        candidate = root.parent / journal.candidate
        present = [
            item for item in (root, previous, candidate) if item.exists() or item.is_symlink()
        ]
        checksums = {item: tree_checksum(item) for item in present}
        metadata = [(item, git_identity(item)) for item in present]
        owners = [item for item, identity in metadata if identity is not None]
        if journal.git_identity is None:
            if owners:
                raise ValueError("unexpected repository metadata during recovery")
        elif len(owners) != 1 or git_identity(owners[0]) != journal.git_identity:
            raise ValueError("repository metadata identity is ambiguous")

        status: str
        if (
            root in checksums
            and candidate not in checksums
            and checksums[root] == journal.candidate_checksum
        ):
            if previous in checksums and checksums[previous] != journal.previous_checksum:
                raise ValueError("previous generation changed after promotion")
            if owners and owners != [root]:
                raise ValueError("completed generation is missing repository metadata")
            status = "complete"
        elif candidate in checksums and checksums[candidate] == journal.candidate_checksum:
            if (
                root in checksums
                and previous not in checksums
                and checksums[root] == journal.previous_checksum
            ):
                if owners and owners != [root]:
                    raise ValueError("original generation is missing repository metadata")
                status = "original"
            elif (
                root not in checksums
                and previous in checksums
                and checksums[previous] == journal.previous_checksum
            ):
                status = "restore_previous"
            elif (
                root not in checksums
                and previous not in checksums
                and journal.previous_checksum is None
            ):
                status = "unpromoted_initial"
            else:
                raise ValueError("promotion generations are ambiguous")
        else:
            raise ValueError("promotion generation checksum mismatch")

        retained: str | None = None
        if apply:
            if status == "restore_previous":
                if owners == [candidate]:
                    (candidate / ".git").rename(previous / ".git")
                    sync_directory(candidate)
                    sync_directory(previous)
                previous.rename(root)
                sync_directory(root.parent)
            elif status == "complete" and previous.exists():
                retained_path = root.with_name(f".{root.name}-recovered-{journal.candidate}")
                if retained_path.exists() or retained_path.is_symlink():
                    raise ValueError("recovered generation destination already exists")
                previous.rename(retained_path)
                sync_directory(root.parent)
                retained = retained_path.name
            clear_journal(root)
        return {
            "status": status,
            "applied": apply,
            "retained_previous": retained,
            "retained_candidate": candidate.name if candidate.exists() else None,
        }
