from __future__ import annotations

import json
from pathlib import Path

from click import unstyle
from typer.testing import CliRunner

from breachgazette.cli import app

runner = CliRunner()
REVIEW_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "reviews"


def test_source_policy_cli_commands_are_machine_readable() -> None:
    inspected = runner.invoke(app, ["inspect-sources", "--json"])
    assert inspected.exit_code == 0
    assert "oaic_ndb" in json.loads(inspected.stdout)
    validated = runner.invoke(app, ["validate-source-policies", "--json"])
    assert validated.exit_code == 0
    assert json.loads(validated.stdout) == {"policies": 10, "valid": True}
    monitoring = runner.invoke(app, ["validate-monitoring", "--json"])
    assert monitoring.exit_code == 0
    assert json.loads(monitoring.stdout)["sources"] == 9
    aliases = runner.invoke(
        app,
        [
            "validate-aliases",
            "--catalogue",
            str(REVIEW_FIXTURES / "organization-aliases.yml"),
            "--json",
        ],
    )
    assert aliases.exit_code == 0
    assert json.loads(aliases.stdout) == {
        "approved": 0,
        "decisions": 0,
        "rejected": 0,
        "valid": True,
    }
    decision = runner.invoke(
        app,
        ["alias-decision-id", "Example Services", "Example Group", "--json"],
    )
    assert decision.exit_code == 0
    assert json.loads(decision.stdout)["decision_id"].startswith("alias_")
    relationships = runner.invoke(
        app,
        [
            "validate-relationships",
            "--catalogue",
            str(REVIEW_FIXTURES / "relationship-decisions.yml"),
            "--json",
        ],
    )
    assert relationships.exit_code == 0
    assert json.loads(relationships.stdout) == {
        "confirmed_related": 0,
        "decisions": 0,
        "rejected": 0,
        "unresolved": 0,
        "valid": True,
    }
    relationship_id = runner.invoke(
        app,
        [
            "relationship-decision-id",
            "rel_111111111111111111111111",
            "--record-id",
            "one",
            "--record-id",
            "two",
            "--json",
        ],
    )
    assert relationship_id.exit_code == 0
    assert json.loads(relationship_id.stdout)["decision_id"].startswith("relationship_")


def test_cli_requires_a_private_data_root() -> None:
    result = runner.invoke(app, ["compare", "--json"], color=True)
    assert result.exit_code != 0
    assert "--data-root" in unstyle(result.output)


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
    proposals_path = root / "reports" / "proposals.json"
    proposals = runner.invoke(
        app,
        [
            "propose-aliases",
            "--data-root",
            str(root),
            "--catalogue",
            str(REVIEW_FIXTURES / "organization-aliases.yml"),
            "--output",
            str(proposals_path),
            "--json",
        ],
    )
    assert proposals.exit_code == 0
    assert json.loads(proposals.stdout)["proposal_count"] == 0
    assert proposals_path.is_file()
    quality = runner.invoke(
        app,
        ["quality-report", "--data-root", str(root), "--json"],
    )
    assert quality.exit_code == 2
    assert json.loads(quality.stdout) == {
        "error": "data_quality_error",
        "message": (
            "publication quality gates failed: required_sources_present, "
            "source_snapshots_present, fixture_isolation"
        ),
        "passed": False,
    }
    assert "Traceback" not in quality.output
    publication = runner.invoke(
        app,
        [
            "build-site-data",
            "--data-root",
            str(root),
            "--output",
            str(tmp_path / "publication"),
            "--json",
        ],
    )
    assert publication.exit_code == 2
    assert json.loads(publication.stdout) == {
        "error": "data_quality_error",
        "message": "production site data requires real source-derived state",
        "passed": False,
    }
    assert "Traceback" not in publication.output
