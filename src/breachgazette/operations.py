"""Transactional private-state update cycles and sanitized operator summaries."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from breachgazette.contracts import SourceHealthReport, SourceSnapshot
from breachgazette.monitoring import (
    build_source_health_report,
    write_source_health_report,
)
from breachgazette.pipeline import ADAPTERS, _update_source_generation, update_all
from breachgazette.publish.builder import audit_public_tree, build_site_data
from breachgazette.retention import compact_state, state_inventory
from breachgazette.state import PrivateStateStore
from breachgazette.state.transaction import copy_candidate, promote_candidate, state_lock
from breachgazette.utils import atomic_write_json, read_json

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


def run_update_cycle(
    *,
    data_root: Path,
    sources: list[str] | None = None,
    promote: bool = False,
    updater: UpdateFunction = update_all,
    builder: BuildFunction = build_site_data,
    auditor: AuditFunction = audit_public_tree,
    attempt_report: Path | None = None,
) -> dict[str, Any]:
    with state_lock(data_root):
        return _run_update_cycle_locked(
            data_root=data_root,
            sources=sources,
            promote=promote,
            updater=updater,
            builder=builder,
            auditor=auditor,
            attempt_report=attempt_report,
        )


def _run_update_cycle_locked(
    *,
    data_root: Path,
    sources: list[str] | None,
    promote: bool,
    updater: UpdateFunction,
    builder: BuildFunction,
    auditor: AuditFunction,
    attempt_report: Path | None,
) -> dict[str, Any]:
    root = _bounded_root(data_root)
    selected = sources or list(ADAPTERS)
    if len(set(selected)) != len(selected) or set(selected) - set(ADAPTERS):
        raise ValueError("update-cycle sources must be distinct supported identifiers")
    if attempt_report is not None:
        report_target = attempt_report.resolve()
        if report_target == root or root in report_target.parents:
            raise ValueError("attempt reports must be outside the authoritative data root")
    started = datetime.now(UTC)
    production_store = PrivateStateStore(root)
    production_snapshots = {
        source_id: production_store.load_snapshot(source_id) for source_id in selected
    }
    initial_inventory = state_inventory(root)
    if not initial_inventory["within_size_limit"]:
        raise RuntimeError("private state exceeds its reviewed size bound")
    candidate = copy_candidate(root)
    publication = Path(tempfile.mkdtemp(prefix=".breachgazette-publication-", dir=root.parent))
    phase = "retrieval"
    succeeded = False
    attempted: dict[str, str] = {}
    diagnostics: list[dict[str, Any]] = []
    try:
        if updater is update_all:
            updates = []
            for source_id in selected:
                attempted[source_id] = "failed"
                updates.append(_update_source_generation(source_id, data_root=candidate))
                attempted[source_id] = "complete"
        else:
            updates = updater(data_root=candidate, sources=sources)
            attempted.update({item["source_id"]: "complete" for item in updates})
        phase = "health_validation"
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
        phase = "publication_validation"
        build = builder(data_root=candidate, output=publication)
        phase = "public_tree_validation"
        audit = auditor(publication)
        phase = "retention_validation"
        compact_state(candidate, apply=True)
        inventory = state_inventory(candidate)
        if not inventory["within_size_limit"]:
            raise RuntimeError("candidate private state exceeds its reviewed size bound")
        if promote:
            phase = "promotion"
            _capture_attempt_sources(
                candidate, selected, started, attempted, diagnostics, production_snapshots
            )
            promote_candidate(root, candidate)
        succeeded = True
        return {
            "schema_version": "1.0",
            "promoted": promote,
            "sources_updated": len(updates),
            "quality_passed": bool(build.get("quality_passed")),
            "public_audit_passed": bool(audit.get("passed")),
            "state_size_bytes": inventory["size_bytes"],
        }
    finally:
        try:
            if not diagnostics:
                _capture_attempt_sources(
                    candidate, selected, started, attempted, diagnostics, production_snapshots
                )
            if attempt_report is not None:
                atomic_write_json(
                    attempt_report,
                    {
                        "schema_version": "1.0",
                        "started_at": started,
                        "completed_at": datetime.now(UTC),
                        "passed": succeeded,
                        "promoted": succeeded and promote,
                        "phase": "complete" if succeeded else phase,
                        "sources": diagnostics,
                        "limitations": [
                            "Attempt status is separate from the last successfully "
                            "published state.",
                            "A publication failure does not mean every source retrieval failed.",
                            "No source records, retrieval URLs or exception text are included.",
                        ],
                    },
                )
        finally:
            shutil.rmtree(candidate, ignore_errors=True)
            shutil.rmtree(publication, ignore_errors=True)


def _capture_attempt_sources(
    candidate: Path,
    selected: list[str],
    started: datetime,
    attempted: dict[str, str],
    output: list[dict[str, Any]],
    production_snapshots: dict[str, SourceSnapshot | None],
) -> None:
    store = PrivateStateStore(candidate)
    for source_id in selected:
        checkpoint = store.load_checkpoint(source_id)
        snapshot = store.load_snapshot(source_id)
        production = production_snapshots[source_id]
        status = attempted.get(source_id, "not_attempted")
        if checkpoint is not None and checkpoint.attempted_at >= started:
            status = checkpoint.status
        output.append(
            {
                "source_id": source_id,
                "status": status,
                "attempt_record_count": snapshot.records_accepted
                if snapshot and status == "complete"
                else None,
                "production_record_count": production.records_accepted if production else 0,
                "last_successful_production_update": production.completed_at
                if production
                else None,
            }
        )


def attempt_summary(path: Path) -> str:
    report = read_json(path)
    if not isinstance(report, dict) or report.get("schema_version") != "1.0":
        raise ValueError("attempt report is invalid")
    allowed = {"complete", "failed", "in_progress", "not_attempted"}
    phases = {
        "retrieval": "source retrieval",
        "health_validation": "source health validation",
        "publication_validation": "publication validation",
        "public_tree_validation": "public tree validation",
        "retention_validation": "retention validation",
        "promotion": "generation promotion",
        "complete": "complete",
    }
    if report.get("phase") not in phases:
        raise ValueError("attempt summary contains an unsupported phase")
    lines = ["## Update attempt", "", "| Source | Attempt |", "| --- | --- |"]
    for entry in report.get("sources", []):
        if entry.get("source_id") not in ADAPTERS or entry.get("status") not in allowed:
            raise ValueError("attempt summary contains an unsupported status or source")
        lines.append(f"| `{entry['source_id']}` | {entry['status']} |")
    lines.extend(
        [
            "",
            f"Stage: {phases[report['phase']]}.",
            f"Result: {'passed' if report.get('passed') is True else 'failed'}.",
        ]
    )
    return "\n".join(lines) + "\n"


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
