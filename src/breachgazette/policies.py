"""Load and validate the versioned source policy catalogue."""

from __future__ import annotations

import json
from pathlib import Path

from breachgazette.contracts import SourcePolicy


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_source_policies(root: Path | None = None) -> dict[str, SourcePolicy]:
    policy_root = (root or repository_root()) / "sources" / "policies"
    policies: dict[str, SourcePolicy] = {}
    for path in sorted(policy_root.glob("*.json")):
        policy = SourcePolicy.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if policy.source_id in policies:
            raise ValueError(f"duplicate source policy: {policy.source_id}")
        policies[policy.source_id] = policy
    if not policies:
        raise ValueError("no source policies were found")
    return policies
