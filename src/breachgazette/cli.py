"""Breach Gazette command-line interface."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

import typer

from breachgazette.contracts import NormalizedNotification, RegulatoryAction
from breachgazette.entities import (
    alias_decision_id,
    build_alias_proposal_report,
    load_alias_catalogue,
)
from breachgazette.monitoring import (
    build_source_health_report,
    load_monitoring_catalogue,
    write_source_health_report,
)
from breachgazette.operations import run_update_cycle, source_health_summary
from breachgazette.pipeline import (
    ADAPTERS,
    compare_summary,
    ingest_fixture,
    update_all,
    update_source,
)
from breachgazette.policies import load_source_policies
from breachgazette.publish.builder import audit_public_tree, build_site_data
from breachgazette.quality import build_quality_report
from breachgazette.relationships import (
    generate_candidates,
    load_relationship_catalogue,
    relationship_decision_id,
)
from breachgazette.retention import (
    compact_state,
    create_state_backup,
    restore_state_backup,
    state_inventory,
)
from breachgazette.state import PrivateStateStore
from breachgazette.utils import atomic_write_json, normalize_organization_name

app = typer.Typer(
    no_args_is_help=True,
    help="Bounded official-source ingestion and static publication for Breach Gazette.",
)


def _data_root(value: Path | None) -> Path:
    if value is not None:
        return value
    configured = os.environ.get("BREACHGAZETTE_DATA_ROOT")
    if not configured:
        raise typer.BadParameter(
            "--data-root or BREACHGAZETTE_DATA_ROOT is required for stateful commands"
        )
    return Path(configured)


def _emit(value: Any, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(value, indent=2, sort_keys=True, default=str))
    elif isinstance(value, dict):
        for key, item in value.items():
            typer.echo(f"{key}: {item}")
    else:
        typer.echo(value)


@app.command("inspect-sources")
def inspect_sources(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    policies = load_source_policies()
    payload = {
        source_id: {
            "implemented": policy.implemented,
            "publication_level": policy.publication_level,
            "coverage_type": policy.coverage_type,
            "source_url": str(policy.source_url),
            "redistribution_decision": policy.redistribution_decision,
        }
        for source_id, policy in sorted(policies.items())
    }
    _emit(payload, json_output=json_output)


@app.command("validate-source-policies")
def validate_source_policies(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    policies = load_source_policies()
    required = set(ADAPTERS) | {"hhs"}
    missing = required - set(policies)
    if missing:
        raise typer.Exit(code=2)
    _emit({"valid": True, "policies": len(policies)}, json_output=json_output)


@app.command("validate-monitoring")
def validate_monitoring(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    catalogue = load_monitoring_catalogue()
    _emit(
        {
            "valid": True,
            "sources": len(catalogue.sources),
            "schedule_utc": catalogue.schedule_utc,
        },
        json_output=json_output,
    )


@app.command("validate-aliases")
def validate_aliases(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    catalogue: Annotated[Path | None, typer.Option("--catalogue")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    selected = load_alias_catalogue(
        catalogue or _data_root(data_root) / "reviews" / "organization-aliases.yml"
    )
    _emit(
        {
            "valid": True,
            "decisions": len(selected.decisions),
            "approved": sum(decision.status == "approved" for decision in selected.decisions),
            "rejected": sum(decision.status == "rejected" for decision in selected.decisions),
        },
        json_output=json_output,
    )


@app.command("validate-relationships")
def validate_relationships(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    catalogue: Annotated[Path | None, typer.Option("--catalogue")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    selected = load_relationship_catalogue(
        catalogue or _data_root(data_root) / "reviews" / "relationship-decisions.yml"
    )
    _emit(
        {
            "valid": True,
            "decisions": len(selected.decisions),
            "confirmed_related": sum(
                decision.status == "confirmed_related" for decision in selected.decisions
            ),
            "rejected": sum(
                decision.status == "rejected" for decision in selected.decisions
            ),
            "unresolved": sum(
                decision.status == "unresolved" for decision in selected.decisions
            ),
        },
        json_output=json_output,
    )


@app.command("relationship-decision-id")
def relationship_decision_id_command(
    candidate_id: Annotated[str, typer.Argument()],
    record_id: Annotated[list[str], typer.Option("--record-id")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(
        {"decision_id": relationship_decision_id(candidate_id, record_id)},
        json_output=json_output,
    )


@app.command("alias-decision-id")
def alias_decision_id_command(
    alias_name: Annotated[str, typer.Argument()],
    canonical_name: Annotated[str, typer.Argument()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(
        {
            "decision_id": alias_decision_id(alias_name, canonical_name),
            "alias_normalized": normalize_organization_name(alias_name),
            "canonical_normalized": normalize_organization_name(canonical_name),
        },
        json_output=json_output,
    )


@app.command("propose-aliases")
def propose_aliases_command(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    catalogue: Annotated[Path | None, typer.Option("--catalogue")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=2_000)] = 500,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    root = _data_root(data_root)
    store = PrivateStateStore(root)
    notifications = [
        NormalizedNotification.model_validate(record.model_dump(mode="json"))
        for source_id in store.source_ids()
        for record in store.load_records(source_id)
        if getattr(record, "record_type", None) == "notification"
    ]
    regulatory_actions = [
        RegulatoryAction.model_validate(record.model_dump(mode="json"))
        for source_id in store.source_ids()
        for record in store.load_records(source_id)
        if getattr(record, "record_type", None) == "regulatory"
    ]
    report = build_alias_proposal_report(
        notifications,
        regulatory_actions,
        catalogue=load_alias_catalogue(
            catalogue or root / "reviews" / "organization-aliases.yml"
        ),
        limit=limit,
    )
    report_path = output or root / "reports" / "alias-proposals.json"
    atomic_write_json(report_path, report)
    _emit(
        {
            "output": str(report_path),
            "proposal_count": report["proposal_count"],
            "limitations": report["limitations"],
        },
        json_output=json_output,
    )


@app.command()
def update(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    result = update_all(data_root=_data_root(data_root), sources=source)
    _emit(result, json_output=json_output)


@app.command("update-source")
def update_one_source(
    source: Annotated[str, typer.Argument()],
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(
        update_source(source, data_root=_data_root(data_root)),
        json_output=json_output,
    )


@app.command("update-cycle")
def update_cycle_command(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
    promote: Annotated[bool, typer.Option("--promote")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(
        run_update_cycle(
            data_root=_data_root(data_root),
            sources=source,
            promote=promote,
        ),
        json_output=json_output,
    )


@app.command("ingest-fixture")
def ingest_fixture_command(
    fixture: Annotated[Path, typer.Argument(exists=True, readable=True)],
    data_root: Annotated[Path, typer.Option("--data-root")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(
        ingest_fixture(fixture, data_root=data_root),
        json_output=json_output,
    )


@app.command()
def compare(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(compare_summary(data_root=_data_root(data_root)), json_output=json_output)


@app.command("resolve-entities")
def resolve_entities_command(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    store = PrivateStateStore(_data_root(data_root))
    notifications = [
        NormalizedNotification.model_validate(record.model_dump(mode="json"))
        for source_id in store.source_ids()
        for record in store.load_records(source_id)
        if getattr(record, "record_type", None) == "notification"
    ]
    candidates = generate_candidates(notifications)
    _emit(
        {"notification_records": len(notifications), "relationship_candidates": len(candidates)},
        json_output=json_output,
    )


@app.command("build-site-data")
def build_site_data_command(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    output: Annotated[Path, typer.Option("--output")] = Path("site-data"),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(
        build_site_data(data_root=_data_root(data_root), output=output),
        json_output=json_output,
    )


@app.command("audit-public-tree")
def audit_public_tree_command(
    path: Annotated[Path, typer.Argument()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(audit_public_tree(path), json_output=json_output)


@app.command("check-source-links")
def check_source_links(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    store = PrivateStateStore(_data_root(data_root))
    unsafe: list[str] = []
    checked = 0
    for source_id in store.source_ids():
        for record in store.load_records(source_id):
            checked += 1
            if not str(record.source_url).startswith("https://"):
                unsafe.append(f"{source_id}:{record.source_record_id}")
    if unsafe:
        raise typer.Exit(code=2)
    _emit({"checked": checked, "unsafe": 0}, json_output=json_output)


@app.command("quality-report")
def quality_report_command(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    store = PrivateStateStore(_data_root(data_root))
    records = {source_id: store.load_records(source_id) for source_id in store.source_ids()}
    report = build_quality_report(
        dataset_class=str(store.dataset_class()),
        records_by_source=records,
        snapshots=store.all_snapshots(),
    )
    _emit(report.model_dump(mode="json"), json_output=json_output)


@app.command("source-health")
def source_health_command(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    report = build_source_health_report(data_root=_data_root(data_root))
    if output is not None:
        write_source_health_report(report, output)
    _emit(report.model_dump(mode="json"), json_output=json_output)
    if not report.passed:
        raise typer.Exit(code=2)


@app.command("source-health-summary")
def source_health_summary_command(
    report: Annotated[Path, typer.Argument(exists=True, readable=True)],
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    summary = source_health_summary(report)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(summary, encoding="utf-8")
    typer.echo(summary, nl=False)


@app.command("state-inventory")
def state_inventory_command(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(state_inventory(_data_root(data_root)), json_output=json_output)


@app.command("compact-state")
def compact_state_command(
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    apply: Annotated[bool, typer.Option("--apply")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(
        compact_state(_data_root(data_root), apply=apply),
        json_output=json_output,
    )


@app.command("backup-state")
def backup_state_command(
    output: Annotated[Path, typer.Argument()],
    data_root: Annotated[Path | None, typer.Option("--data-root")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(
        create_state_backup(_data_root(data_root), output),
        json_output=json_output,
    )


@app.command("restore-state")
def restore_state_command(
    archive: Annotated[Path, typer.Argument(exists=True, readable=True)],
    destination: Annotated[Path, typer.Argument()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _emit(
        restore_state_backup(archive, destination),
        json_output=json_output,
    )


if __name__ == "__main__":
    app()
