"""Breach Gazette command-line interface."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

import typer

from breachgazette.contracts import NormalizedNotification
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
from breachgazette.relationships import generate_candidates
from breachgazette.state import PrivateStateStore

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


if __name__ == "__main__":
    app()
