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
    assert "Create isolated candidate state" in workflow
    assert "rsync -a --exclude .git .private-production-data/" in workflow
    assert "steps.candidate_quality.outcome == 'success'" in workflow
    assert "git push origin HEAD" in workflow
    assert workflow.index("Promote complete candidate") < workflow.index("git push origin HEAD")
