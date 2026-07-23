"""Load and validate the versioned source policy catalogue."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from breachgazette.contracts import SourcePolicy

MAX_RIGHTS_REVIEW_AGE_DAYS = 366


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_source_policies(root: Path | None = None) -> dict[str, SourcePolicy]:
    policy_root = (root or repository_root()) / "sources" / "policies"
    policies: dict[str, SourcePolicy] = {}
    for path in sorted(policy_root.glob("*.json")):
        policy = SourcePolicy.model_validate(json.loads(path.read_text(encoding="utf-8")))
        review_age = (date.today() - policy.rights_reviewed_on).days
        if review_age < 0:
            raise ValueError(f"source policy rights review is future-dated: {policy.source_id}")
        if review_age > MAX_RIGHTS_REVIEW_AGE_DAYS:
            raise ValueError(f"source policy rights review is stale: {policy.source_id}")
        if policy.source_id in policies:
            raise ValueError(f"duplicate source policy: {policy.source_id}")
        policies[policy.source_id] = policy
    if not policies:
        raise ValueError("no source policies were found")
    return policies
