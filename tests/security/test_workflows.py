from __future__ import annotations

import re
from pathlib import Path

WORKFLOW_ROOT = Path(__file__).resolve().parents[2] / ".github" / "workflows"
SHA_PIN = re.compile(r"^\s*uses:\s+[^@\s]+@[0-9a-f]{40}(?:\s+#.*)?$")


def test_every_action_reference_is_pinned_to_a_full_commit_sha() -> None:
    action_references = [
        line
        for workflow in WORKFLOW_ROOT.glob("*.yml")
        for line in workflow.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("uses:")
    ]
    assert action_references
    assert all(SHA_PIN.match(line) for line in action_references)


def test_scheduled_private_update_is_opt_in_and_candidate_gated() -> None:
    workflow = (WORKFLOW_ROOT / "scheduled-private-update.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "vars.BREACHGAZETTE_SCHEDULE_ENABLED == 'true'" in workflow
    assert "default: false" in workflow
    assert "breachgazette update-cycle --data-root .private-production-data --promote" in workflow
    assert "steps.update_cycle.outcome == 'success'" in workflow
    assert "source-health-summary" in workflow
    assert "GITHUB_STEP_SUMMARY" in workflow
    assert workflow.index("source-health-summary") < workflow.index(
        "Fail incomplete update after preserving health report"
    )
    assert "git push origin HEAD" in workflow
    assert workflow.index("Verify and promote an isolated candidate") < workflow.index(
        "git push origin HEAD"
    )
    assert "reviews" in workflow
    assert "breachgazette-update@users.noreply.github.com" in workflow


def test_ci_covers_private_catalogue_contracts_and_all_browser_engines() -> None:
    workflow = (WORKFLOW_ROOT / "ci.yml").read_text(encoding="utf-8")
    assert "tests/fixtures/reviews/organization-aliases.yml" in workflow
    assert "tests/fixtures/reviews/relationship-decisions.yml" in workflow
    assert "playwright install --with-deps chromium firefox webkit" in workflow
    assert "npm run test:e2e:ci" in workflow
    assert 'BREACHGAZETTE_PAGES_BUILD: "1"' in workflow


def test_pages_build_is_explicit_and_budgeted() -> None:
    workflow = (WORKFLOW_ROOT / "pages.yml").read_text(encoding="utf-8")
    assert 'BREACHGAZETTE_PAGES_BUILD: "1"' in workflow
    assert "npm run build:budget" in workflow
