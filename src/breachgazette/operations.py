"""Transactional private-state update cycles and sanitized operator summaries."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from breachgazette.contracts import SourceHealthReport
from breachgazette.monitoring import (
    build_source_health_report,
    write_source_health_report,
)
from breachgazette.pipeline import update_all
from breachgazette.publish.builder import audit_public_tree, build_site_data
from breachgazette.retention import compact_state, state_inventory
from breachgazette.utils import read_json

UpdateFunction = Callable[..., list[dict[str, Any]]]
BuildFunction = Callable[..., dict[str, Any]]
AuditFunction = Callable[[Path], dict[str, Any]]


def _bounded_root(root: Path) -> Path:
    resolved = root.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise ValueError("private-state root is too broad")
    if not resolved.exists() or not resolved.is_dir() or resolved.is_symlink():
        raise ValueError("private-state root must be an existing regular directory")
    return resolved


def _copy_candidate(root: Path) -> Path:
    candidate = Path(
        tempfile.mkdtemp(prefix=f".{root.name}-candidate-", dir=root.parent)
    )
    shutil.copytree(
        root,
        candidate,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".git"),
    )
    return candidate


def _promote_candidate(root: Path, candidate: Path) -> None:
    backup = root.with_name(f".{root.name}-previous")
    if backup.exists():
        raise ValueError("a previous update backup already exists")
    root.rename(backup)
    try:
        git_directory = backup / ".git"
        if git_directory.exists():
            git_directory.rename(candidate / ".git")
        candidate.rename(root)
    except BaseException:
        if root.exists() and not candidate.exists():
            root.rename(candidate)
        candidate_git = candidate / ".git"
        if candidate_git.exists() and not (backup / ".git").exists():
            candidate_git.rename(backup / ".git")
        backup.rename(root)
        raise
    shutil.rmtree(backup)


def run_update_cycle(
    *,
    data_root: Path,
    sources: list[str] | None = None,
    promote: bool = False,
    updater: UpdateFunction = update_all,
    builder: BuildFunction = build_site_data,
    auditor: AuditFunction = audit_public_tree,
) -> dict[str, Any]:
    root = _bounded_root(data_root)
    initial_inventory = state_inventory(root)
    if not initial_inventory["within_size_limit"]:
        raise RuntimeError("private state exceeds its reviewed size bound")
    candidate = _copy_candidate(root)
    publication = Path(
        tempfile.mkdtemp(prefix=".breachgazette-publication-", dir=root.parent)
    )
    try:
        updates = updater(data_root=candidate, sources=sources)
        health = build_source_health_report(data_root=candidate)
        report_path = candidate / "reports" / "source-health.json"
        write_source_health_report(health, report_path)
        history_path = (
            candidate
            / "reports"
            / "history"
            / f"source-health-{health.generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        write_source_health_report(health, history_path)
        if not health.passed:
            raise RuntimeError("candidate source-health gates failed")
        build = builder(data_root=candidate, output=publication)
        audit = auditor(publication)
        compact_state(candidate, apply=True)
        inventory = state_inventory(candidate)
        if not inventory["within_size_limit"]:
            raise RuntimeError("candidate private state exceeds its reviewed size bound")
        if promote:
            _promote_candidate(root, candidate)
        return {
            "schema_version": "1.0",
            "promoted": promote,
            "sources_updated": len(updates),
            "quality_passed": bool(build.get("quality_passed")),
            "public_audit_passed": bool(audit.get("passed")),
            "state_size_bytes": inventory["size_bytes"],
        }
    finally:
        shutil.rmtree(candidate, ignore_errors=True)
        shutil.rmtree(publication, ignore_errors=True)


def source_health_summary(path: Path) -> str:
    payload = read_json(path)
    report = SourceHealthReport.model_validate(payload)
    lines = [
        "## Breach Gazette source health",
        "",
        "| Source | Status | Records |",
        "| --- | --- | ---: |",
    ]
    for entry in sorted(report.sources, key=lambda item: item.source_id):
        lines.append(f"| `{entry.source_id}` | {entry.status} | {entry.record_count} |")
    lines.extend(
        [
            "",
            f"Overall result: **{'passed' if report.passed else 'failed'}**.",
            "",
            "This summary omits record contents, checksums, retrieval URLs, and timestamps.",
        ]
    )
    return "\n".join(lines) + "\n"
