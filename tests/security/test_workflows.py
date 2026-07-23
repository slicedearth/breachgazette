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
    assert "secrets.BREACHGAZETTE_DATA_WRITE_KEY" in workflow
    assert "secrets.BREACHGAZETTE_DATA_READ_KEY" not in workflow
    assert "reviews" in workflow
    assert "breachgazette-update@users.noreply.github.com" in workflow


def test_ci_covers_private_catalogue_contracts_and_all_browser_engines() -> None:
    workflow = (WORKFLOW_ROOT / "ci.yml").read_text(encoding="utf-8")
    assert "tests/fixtures/reviews/organization-aliases.yml" in workflow
    assert "tests/fixtures/reviews/relationship-decisions.yml" in workflow
    assert "playwright install --with-deps chromium firefox webkit" in workflow
    assert "npm run test:e2e:ci" in workflow
    assert 'BREACHGAZETTE_SITE_URL: "https://breachgazette.example"' in workflow


def test_netlify_build_is_explicit_budgeted_and_receives_only_public_output() -> None:
    workflow = (WORKFLOW_ROOT / "netlify.yml").read_text(encoding="utf-8")
    assert "secrets.BREACHGAZETTE_DATA_READ_KEY" in workflow
    assert "secrets.BREACHGAZETTE_DATA_WRITE_KEY" not in workflow
    assert "persist-credentials: false" in workflow
    assert "vars.BREACHGAZETTE_SITE_URL" in workflow
    assert "npm run build:budget" in workflow
    assert "breachgazette audit-public-tree dist --json" in workflow
    assert "netlify-cli" not in workflow
    assert 'zip -q -r -X -D "$RUNNER_TEMP/breachgazette-site.zip" .' in workflow
    assert "Content-Type: application/zip" in workflow
    assert '--data-binary "@$RUNNER_TEMP/breachgazette-site.zip"' in workflow
    assert "/deploys?production=true" in workflow
    assert workflow.index("breachgazette audit-public-tree dist --json") < workflow.index(
        "breachgazette-site.zip"
    )


def test_netlify_headers_enforce_static_site_security_policy() -> None:
    root = WORKFLOW_ROOT.parents[1]
    config = (root / "netlify.toml").read_text(encoding="utf-8")
    headers = (root / "site" / "public" / "_headers").read_text(encoding="utf-8")
    assert 'publish = "site/dist"' in config
    assert "frame-ancestors 'none'" in headers
    assert "Strict-Transport-Security: max-age=31536000" in headers
    assert "X-Content-Type-Options: nosniff" in headers
    assert "Referrer-Policy: no-referrer" in headers
