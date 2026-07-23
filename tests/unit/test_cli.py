from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from breachgazette.cli import app

runner = CliRunner()


def test_source_policy_cli_commands_are_machine_readable() -> None:
    inspected = runner.invoke(app, ["inspect-sources", "--json"])
    assert inspected.exit_code == 0
    assert "oaic_ndb" in json.loads(inspected.stdout)
    validated = runner.invoke(app, ["validate-source-policies", "--json"])
    assert validated.exit_code == 0
    assert json.loads(validated.stdout) == {"policies": 7, "valid": True}


def test_cli_requires_a_private_data_root() -> None:
    result = runner.invoke(app, ["compare", "--json"])
    assert result.exit_code != 0
    assert "data-root" in result.output


def test_fixture_and_inventory_cli(tmp_path: Path, notification_factory) -> None:
    record = notification_factory().model_dump(mode="json", exclude={"canonical_organization_id"})
    fixture = tmp_path / "record.json"
    fixture.write_text(
        json.dumps(
            {
                "dataset_class": "test_fixture",
                "source_id": "washington",
                "records": [record],
            }
        ),
        encoding="utf-8",
    )
    root = tmp_path / "fixture-cli"
    ingested = runner.invoke(
        app,
        [
            "ingest-fixture",
            str(fixture),
            "--data-root",
            str(root),
            "--json",
        ],
    )
    assert ingested.exit_code == 0
    assert json.loads(ingested.stdout)["records"] == 1
    compared = runner.invoke(
        app,
        ["compare", "--data-root", str(root), "--json"],
    )
    assert compared.exit_code == 0
    assert json.loads(compared.stdout)["events"] == 0
    links = runner.invoke(
        app,
        ["check-source-links", "--data-root", str(root), "--json"],
    )
    assert links.exit_code == 0
    assert json.loads(links.stdout) == {"checked": 1, "unsafe": 0}
