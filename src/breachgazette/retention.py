"""Bounded private-state inventory, compaction, backup, and restore."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from breachgazette.policies import repository_root
from breachgazette.utils import read_json, sha256_hex


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    managed_directories: tuple[str, ...]
    maximum_history_reports: int = Field(ge=1, le=520)
    maximum_state_bytes: int = Field(ge=1)
    maximum_archive_bytes: int = Field(ge=1)


@dataclass(frozen=True)
class StateFile:
    relative_path: str
    size_bytes: int
    checksum_sha256: str


def _file_checksum(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def load_retention_policy(path: Path | None = None) -> RetentionPolicy:
    policy_path = path or repository_root() / "sources" / "retention.json"
    payload = read_json(policy_path)
    if not isinstance(payload, dict):
        raise ValueError("private-state retention policy is missing or invalid")
    policy = RetentionPolicy.model_validate(payload)
    if policy.schema_version != "1.0":
        raise ValueError("unsupported private-state retention policy schema")
    if len(set(policy.managed_directories)) != len(policy.managed_directories):
        raise ValueError("retention managed directories must be unique")
    for name in policy.managed_directories:
        if not name or Path(name).name != name or name.startswith("."):
            raise ValueError("retention managed directories must be simple names")
    return policy


def _bounded_root(root: Path) -> Path:
    resolved = root.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise ValueError("private-state root is too broad")
    return resolved


def _managed_files(root: Path, policy: RetentionPolicy) -> list[StateFile]:
    resolved = _bounded_root(root)
    files: list[StateFile] = []
    for directory in policy.managed_directories:
        managed_root = resolved / directory
        if managed_root.is_symlink():
            raise ValueError(f"managed path must not be a symbolic link: {directory}")
        if not managed_root.exists():
            continue
        for path in sorted(managed_root.rglob("*")):
            if path.is_symlink():
                raise ValueError(
                    f"private state must not contain symbolic links: {path.relative_to(resolved)}"
                )
            if not path.is_file():
                continue
            relative = path.relative_to(resolved).as_posix()
            size, checksum = _file_checksum(path)
            files.append(
                StateFile(
                    relative_path=relative,
                    size_bytes=size,
                    checksum_sha256=checksum,
                )
            )
    return files


def state_inventory(root: Path, *, policy: RetentionPolicy | None = None) -> dict[str, Any]:
    selected = policy or load_retention_policy()
    files = _managed_files(root, selected)
    total = sum(item.size_bytes for item in files)
    return {
        "schema_version": "1.0",
        "files": len(files),
        "size_bytes": total,
        "within_size_limit": total <= selected.maximum_state_bytes,
        "managed_directories": list(selected.managed_directories),
        "checksums": {
            item.relative_path: item.checksum_sha256 for item in files
        },
    }


def plan_compaction(
    root: Path,
    *,
    policy: RetentionPolicy | None = None,
) -> list[Path]:
    selected = policy or load_retention_policy()
    history = _bounded_root(root) / "reports" / "history"
    if history.is_symlink():
        raise ValueError("report history must not be a symbolic link")
    if not history.exists():
        return []
    reports: list[Path] = []
    for path in sorted(history.glob("source-health-*.json")):
        if path.is_symlink() or not path.is_file():
            raise ValueError("report history may contain only regular report files")
        reports.append(path)
    remove_count = max(0, len(reports) - selected.maximum_history_reports)
    return reports[:remove_count]


def compact_state(
    root: Path,
    *,
    apply: bool = False,
    policy: RetentionPolicy | None = None,
) -> dict[str, Any]:
    selected = policy or load_retention_policy()
    resolved = _bounded_root(root)
    candidates = plan_compaction(resolved, policy=selected)
    relative = [path.relative_to(resolved).as_posix() for path in candidates]
    if apply:
        for path in candidates:
            path.unlink()
    return {
        "schema_version": "1.0",
        "applied": apply,
        "removed": relative if apply else [],
        "planned": relative,
        "retained_history_reports": selected.maximum_history_reports,
    }


def create_state_backup(
    root: Path,
    output: Path,
    *,
    policy: RetentionPolicy | None = None,
) -> dict[str, Any]:
    selected = policy or load_retention_policy()
    resolved = _bounded_root(root)
    files = _managed_files(resolved, selected)
    total = sum(item.size_bytes for item in files)
    if total > selected.maximum_archive_bytes:
        raise ValueError("private state exceeds its reviewed archive size bound")
    output_resolved = output.resolve()
    if output_resolved == resolved or resolved in output_resolved.parents:
        raise ValueError("backup output must be outside the private-state root")
    if output.exists():
        raise ValueError("backup output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for item in files:
                info = zipfile.ZipInfo(
                    item.relative_path,
                    date_time=(1980, 1, 1, 0, 0, 0),
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                with (
                    (resolved / item.relative_path).open("rb") as source,
                    archive.open(info, mode="w") as destination,
                ):
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
        archive_size = temporary.stat().st_size
        if archive_size > selected.maximum_archive_bytes:
            raise ValueError("private-state backup exceeded its reviewed archive size bound")
        archive_checksum = _file_checksum(temporary)[1]
        try:
            os.link(temporary, output)
        except FileExistsError as error:
            raise ValueError("backup output already exists") from error
        return {
            "schema_version": "1.0",
            "output": str(output),
            "files": len(files),
            "archive_size_bytes": archive_size,
            "checksum_sha256": archive_checksum,
        }
    finally:
        temporary.unlink(missing_ok=True)


def _safe_archive_path(name: str, policy: RetentionPolicy) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or len(path.parts) < 2
        or path.parts[0] not in policy.managed_directories
    ):
        raise ValueError("private-state backup contains an unsafe path")
    return path


def restore_state_backup(
    archive_path: Path,
    destination: Path,
    *,
    expected_sha256: str,
    policy: RetentionPolicy | None = None,
) -> dict[str, Any]:
    selected = policy or load_retention_policy()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("expected backup SHA-256 must be 64 lowercase hexadecimal characters")
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError("private-state backup must be a regular file")
    archive_checksum = _file_checksum(archive_path)[1]
    if not hmac.compare_digest(archive_checksum, expected_sha256):
        raise ValueError("private-state backup SHA-256 does not match the expected checksum")
    target = _bounded_root(destination)
    if target.exists() and any(target.iterdir()):
        raise ValueError("restore destination must be absent or empty")
    if archive_path.stat().st_size > selected.maximum_archive_bytes:
        raise ValueError("private-state backup exceeds its reviewed size bound")
    extracted_bytes = 0
    extracted_files = 0
    target.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                relative = _safe_archive_path(member.filename, selected)
                mode = member.external_attr >> 16
                if mode and (mode & 0o170000) == 0o120000:
                    raise ValueError("private-state backup must not contain symbolic links")
                extracted_bytes += member.file_size
                if extracted_bytes > selected.maximum_state_bytes:
                    raise ValueError("restored private state exceeds its reviewed size bound")
                target_path = target.joinpath(*relative.parts)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target_path.open("xb") as output:
                    shutil.copyfileobj(source, output)
                extracted_files += 1
        inventory = state_inventory(target, policy=selected)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return {
        "schema_version": "1.0",
        "destination": str(destination),
        "files": extracted_files,
        "size_bytes": extracted_bytes,
        "archive_checksum_sha256": archive_checksum,
        "inventory_checksum": sha256_hex(inventory["checksums"]),
    }
