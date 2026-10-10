"""Opt-in bounded private attempt history, separate from publication state."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from breachgazette.state.transaction import state_lock
from breachgazette.utils import atomic_write_bytes, canonical_json_bytes, sha256_hex

MAX_ATTEMPTS = 53
MAX_REPORT_BYTES = 24_000
ENTRY = re.compile(r"attempt-[0-9]{8}T[0-9]{12}Z-[0-9a-f]{64}\.json")


class AttemptSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: str = Field(pattern=r"^[a-z_]{1,60}$")
    status: Literal["complete", "failed", "in_progress", "not_attempted"]
    attempt_record_count: int | None = Field(ge=0, le=1_000_000)
    production_record_count: int = Field(ge=0, le=1_000_000)
    last_successful_production_update: datetime | None


class AttemptRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1.0"]
    started_at: datetime
    completed_at: datetime
    passed: bool
    promoted: bool
    phase: Literal[
        "retrieval",
        "health_validation",
        "publication_validation",
        "public_tree_validation",
        "retention_validation",
        "promotion",
        "complete",
    ]
    sources: list[AttemptSource] = Field(max_length=20)


def history_target(path: Path, root: Path) -> Path:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("attempt history must not use symbolic links")
    target = path.resolve()
    root = root.resolve()
    if target == root or root in target.parents or target in root.parents:
        raise ValueError("attempt history must be separate from authoritative state")
    for parent in (target, *target.parents):
        if (parent / "pyproject.toml").is_file() and (parent / "src/breachgazette").is_dir():
            raise ValueError("attempt history must be outside the source checkout")
    if target.exists() and not target.is_dir():
        raise ValueError("attempt history must be a directory")
    return target


def append_attempt(path: Path, report: dict[str, Any], *, source_ids: set[str]) -> None:
    # Free-form limitations belong to the current operator report, not retained history.
    record = AttemptRecord.model_validate(
        {key: value for key, value in report.items() if key != "limitations"}
    )
    if any(source.source_id not in source_ids for source in record.sources):
        raise ValueError("attempt history contains an unsupported source")
    if len({source.source_id for source in record.sources}) != len(record.sources):
        raise ValueError("attempt history contains duplicate sources")
    if record.completed_at < record.started_at or (record.promoted and not record.passed):
        raise ValueError("attempt history has inconsistent completion metadata")
    encoded = canonical_json_bytes(record)
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("attempt history report exceeds its byte bound")
    with state_lock(path):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.stat().st_mode & 0o077:
            raise ValueError("attempt history requires owner-only directory permissions")
        files = sorted(path.iterdir())
        if len(files) > MAX_ATTEMPTS + 1:
            raise ValueError("attempt history exceeds its file bound")
        for entry in files:
            if (
                entry.is_symlink()
                or not entry.is_file()
                or not ENTRY.fullmatch(entry.name)
                or entry.stat().st_size > MAX_REPORT_BYTES
            ):
                raise ValueError("attempt history contains an unexpected entry")
            if sha256_hex(entry.read_bytes()) != entry.stem.rsplit("-", 1)[1]:
                raise ValueError("attempt history checksum mismatch")
        name = (
            f"attempt-{record.started_at.strftime('%Y%m%dT%H%M%S%fZ')}-{sha256_hex(encoded)}.json"
        )
        target = path / name
        if not target.exists():
            atomic_write_bytes(target, encoded)
        files = sorted(set([*files, target]))
        for entry in files[:-MAX_ATTEMPTS]:
            entry.unlink()
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
