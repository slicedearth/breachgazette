from __future__ import annotations

import json
import re
from pathlib import Path

WORKFLOW_ROOT = Path(__file__).resolve().parents[2] / ".github" / "workflows"
SHA_PIN = re.compile(r"^\s*uses:\s+[^@\s]+@[0-9a-f]{40}(?:\s+#.*)?$")
LOCAL_WORKFLOW = re.compile(r"^\s*uses:\s+\./\.github/workflows/[a-z0-9-]+\.yml$")


def test_every_external_action_is_pinned_and_local_workflows_are_repository_relative() -> None:
    action_references = [
        line
        for workflow in WORKFLOW_ROOT.glob("*.yml")
        for line in workflow.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("uses:")
    ]
    assert action_references
    assert all(SHA_PIN.match(line) or LOCAL_WORKFLOW.match(line) for line in action_references)


def test_scheduled_private_update_is_opt_in_and_candidate_gated() -> None:
    workflow = (WORKFLOW_ROOT / "scheduled-private-update.yml").read_text(encoding="utf-8")
    update_job, publish_job = workflow.split("\n  publish:\n", maxsplit=1)
    assert "permissions:\n  contents: read" in workflow
    assert "vars.BREACHGAZETTE_SCHEDULE_ENABLED == 'true'" in workflow
    assert "BREACHGAZETTE_SCHEDULE_ENABLED: ${{ vars.BREACHGAZETTE_SCHEDULE_ENABLED }}" in workflow
    assert "vars.BREACHGAZETTE_DATA_REF" in update_job
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
    assert "actions/create-github-app-token@" in update_job
    assert "vars.BREACHGAZETTE_STATE_APP_CLIENT_ID" in update_job
    assert "secrets.BREACHGAZETTE_STATE_APP_PRIVATE_KEY" in update_job
    assert "owner: ${{ github.repository_owner }}" in update_job
    assert "repositories: ${{ vars.BREACHGAZETTE_DATA_REPOSITORY }}" in update_job
    assert "permission-contents: write" in update_job
    assert "permission-contents: read" not in update_job
    assert "token: ${{ steps.state-token.outputs.token }}" in update_job
    assert "ssh-key:" not in update_job
    assert "secrets.BREACHGAZETTE_STATE_APP_PRIVATE_KEY" in publish_job
    assert "needs.update.result == 'success'" in publish_job
    assert "github.event_name == 'schedule' || inputs.persist_private_state" in publish_job
    assert "uses: ./.github/workflows/netlify.yml" in publish_job
    assert "reviews" in workflow
    assert "breachgazette-update@users.noreply.github.com" in workflow


def test_source_drift_can_inspect_every_implemented_adapter() -> None:
    workflow = (WORKFLOW_ROOT / "source-drift.yml").read_text(encoding="utf-8")
    for source_id in (
        "oaic_ndb",
        "nsw_public_notifications",
        "nsw_mndb_aggregate",
        "oaic_regulatory",
        "washington",
        "california",
        "massachusetts",
        "france_cnil",
        "united_kingdom_ico",
    ):
        assert f"          - {source_id}" in workflow


def test_ci_covers_private_catalogue_contracts_and_all_browser_engines() -> None:
    workflow = (WORKFLOW_ROOT / "ci.yml").read_text(encoding="utf-8")
    package = json.loads(
        (WORKFLOW_ROOT.parents[1] / "site" / "package.json").read_text(encoding="utf-8")
    )
    verify_job, browser_job = workflow.split("\n  browser:\n", maxsplit=1)
    image = re.search(
        r"image: mcr\.microsoft\.com/playwright:"
        r"v(?P<version>\d+\.\d+\.\d+)-noble@sha256:[0-9a-f]{64}",
        browser_job,
    )
    assert "ruff check --select S src" in workflow
    assert "python scripts/lock_python.py --check-installed" in workflow
    assert "tests/fixtures/reviews/organization-aliases.yml" in workflow
    assert "tests/fixtures/reviews/relationship-decisions.yml" in workflow
    assert "playwright install" not in workflow
    assert image is not None
    assert image.group("version") == package["devDependencies"]["@playwright/test"]
    assert "options: --user 1001" in browser_job
    assert "npm run test:e2e:ci" not in verify_job
    assert "npm run test:e2e:ci" in browser_job
    assert "uses: ./.github/workflows/codeql.yml" in browser_job
    assert 'BREACHGAZETTE_SITE_URL: "https://breachgazette.example"' in workflow
    codeql = (WORKFLOW_ROOT / "codeql.yml").read_text(encoding="utf-8")
    assert "workflow_call:" in codeql
    assert "pull_request:" not in codeql
    assert "language: [python, javascript-typescript]" in codeql


def test_netlify_build_is_explicit_budgeted_and_receives_only_public_output() -> None:
    workflow = (WORKFLOW_ROOT / "netlify.yml").read_text(encoding="utf-8")
    assert "workflow_call:" in workflow
    assert "workflow_run:" in workflow
    assert "workflows:\n      - CI" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert (
        "github.event.workflow_run.head_repository.full_name == github.repository"
        in workflow
    )
    assert "github.event.workflow_run.head_sha" in workflow
    assert "actions: read" in workflow
    assert "Verify source revision passed the complete CI gate" in workflow
    assert "BREACHGAZETTE_SCHEDULE_ENABLED: ${{ vars.BREACHGAZETTE_SCHEDULE_ENABLED }}" in workflow
    assert "Manual publication requires an exact 40-character private-state commit." in workflow
    assert "vars.BREACHGAZETTE_DATA_REF" in workflow
    assert "steps.data-ref.outputs.data_ref" in workflow
    assert "actions/create-github-app-token@" in workflow
    assert "vars.BREACHGAZETTE_STATE_APP_CLIENT_ID" in workflow
    assert "secrets.BREACHGAZETTE_STATE_APP_PRIVATE_KEY" in workflow
    assert "owner: ${{ github.repository_owner }}" in workflow
    assert "repositories: ${{ vars.BREACHGAZETTE_DATA_REPOSITORY }}" in workflow
    assert "permission-contents: read" in workflow
    assert "permission-contents: write" not in workflow
    assert "token: ${{ steps.state-token.outputs.token }}" in workflow
    assert "ssh-key:" not in workflow
    assert "persist-credentials: false" in workflow
    assert "vars.BREACHGAZETTE_SITE_URL" in workflow
    assert "npm run build:budget" in workflow
    assert "breachgazette audit-public-tree dist --json" in workflow
    assert "netlify-cli" not in workflow
    assert 'zip -q -r -X -D "$RUNNER_TEMP/breachgazette-site.zip" .' in workflow
    assert "Content-Type: application/zip" in workflow
    assert '--data-binary "@$RUNNER_TEMP/breachgazette-site.zip"' in workflow
    assert "/deploys?production=true" in workflow
    assert ".published_at // empty" in workflow
    assert "ready without publishing it" in workflow
    assert ".deploy_ssl_url" in workflow
    assert "Netlify returned an invalid HTTPS deployment URL." in workflow
    assert "Verify live content identity and security headers" in workflow
    assert "Live publication identity did not become current within five minutes" in workflow
    assert 'test "$identity_verified" = "true"' in workflow
    assert "data/publication.json" in workflow
    assert "data/notifications/manifest.json" in workflow
    assert '"/jurisdictions/"' in workflow
    assert '"/france/"' in workflow
    assert '"/source-coverage/"' in workflow
    assert '"/.well-known/security.txt"' in workflow
    assert "steps.publication.outputs.checksum" in workflow
    assert "sha256sum" in workflow
    assert "strict-transport-security: max-age=31536000" in workflow
    assert "x-content-type-options: nosniff" in workflow
    assert "cross-origin-opener-policy: same-origin" in workflow
    assert workflow.index("breachgazette audit-public-tree dist --json") < workflow.index(
        "breachgazette-site.zip"
    )
    assert workflow.index("breachgazette-site.zip") < workflow.index(
        "Verify live content identity and security headers"
    )


def test_netlify_headers_enforce_static_site_security_policy() -> None:
    root = WORKFLOW_ROOT.parents[1]
    config = (root / "netlify.toml").read_text(encoding="utf-8")
    headers = (root / "site" / "public" / "_headers").read_text(encoding="utf-8")
    redirects = (root / "site" / "public" / "_redirects").read_text(encoding="utf-8")
    assert 'publish = "site/dist"' in config
    assert "/.well-known/security.txt /security.txt 200!" in redirects
    assert "frame-ancestors 'none'" in headers
    assert "style-src 'self'" in headers
    assert "'unsafe-inline'" not in headers
    assert "form-action 'none'" in headers
    assert "upgrade-insecure-requests" in headers
    assert "Strict-Transport-Security: max-age=31536000" in headers
    assert "X-Content-Type-Options: nosniff" in headers
    assert "Referrer-Policy: no-referrer" in headers
