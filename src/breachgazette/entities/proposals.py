"""Generate bounded private alias-review proposals without merging identities."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from itertools import combinations
from typing import Any

from breachgazette.contracts import AliasProposal, NormalizedNotification, RegulatoryAction
from breachgazette.entities.catalogue import AliasCatalogue
from breachgazette.utils import normalize_organization_name, stable_id


def _candidate_pairs(keys: list[str]) -> set[tuple[str, str]]:
    blocks: dict[tuple[str, ...], set[str]] = defaultdict(set)
    compact_blocks: dict[str, set[str]] = defaultdict(set)
    for key in keys:
        tokens = tuple(key.split())
        blocks[tokens].add(key)
        if len(tokens) >= 2:
            for index in range(len(tokens)):
                blocks[tokens[:index] + tokens[index + 1 :]].add(key)
        compact_blocks[key.replace(" ", "")].add(key)
    pairs: set[tuple[str, str]] = set()
    for block in [*blocks.values(), *compact_blocks.values()]:
        if 1 < len(block) <= 25:
            pairs.update(combinations(sorted(block), 2))
    return pairs


def propose_alias_reviews(
    notifications: list[NormalizedNotification],
    regulatory_actions: list[RegulatoryAction],
    *,
    catalogue: AliasCatalogue,
    limit: int = 500,
) -> list[AliasProposal]:
    if not 1 <= limit <= 2_000:
        raise ValueError("alias proposal limit must be between 1 and 2000")
    names: dict[str, set[str]] = defaultdict(set)
    labels: dict[str, set[str]] = defaultdict(set)
    for source_id, source_name in [
        *[
            (record.source_id, record.named_entity.source_name)
            for record in notifications
            if record.named_entity.state == "present"
        ],
        *[
            (record.source_id, record.entity.source_name)
            for record in regulatory_actions
            if record.entity.state == "present"
        ],
    ]:
        normalized = normalize_organization_name(source_name)
        if normalized:
            names[normalized].add(source_id)
            labels[normalized].add(source_name)
    proposals: list[AliasProposal] = []
    for left_key, right_key in _candidate_pairs(sorted(names)):
        if frozenset({left_key, right_key}) in catalogue.decided_pairs:
            continue
        combined_sources = sorted(names[left_key] | names[right_key])
        if len(combined_sources) < 2:
            continue
        left_tokens = set(left_key.split())
        right_tokens = set(right_key.split())
        union = left_tokens | right_tokens
        score = len(left_tokens & right_tokens) / len(union) if union else 0
        reasons: list[str] = []
        if left_key.replace(" ", "") == right_key.replace(" ", ""):
            reasons.append("Normalized names differ only by token spacing.")
            score = 1.0
        elif score >= 0.66 and (left_tokens <= right_tokens or right_tokens <= left_tokens):
            reasons.append("One normalized token set contains the other.")
        else:
            continue
        left_name = sorted(labels[left_key], key=lambda value: (value.casefold(), value))[0]
        right_name = sorted(labels[right_key], key=lambda value: (value.casefold(), value))[0]
        proposals.append(
            AliasProposal(
                proposal_id=stable_id(
                    "alias_proposal",
                    left_key,
                    right_key,
                    length=16,
                ),
                left_name=left_name,
                right_name=right_name,
                left_normalized_name=left_key,
                right_normalized_name=right_key,
                source_ids=combined_sources,
                similarity_score=round(score, 4),
                reasons=reasons,
            )
        )
    return sorted(
        proposals,
        key=lambda item: (
            -item.similarity_score,
            item.left_normalized_name,
            item.right_normalized_name,
        ),
    )[:limit]


def build_alias_proposal_report(
    notifications: list[NormalizedNotification],
    regulatory_actions: list[RegulatoryAction],
    *,
    catalogue: AliasCatalogue,
    limit: int = 500,
) -> dict[str, Any]:
    proposals = propose_alias_reviews(
        notifications,
        regulatory_actions,
        catalogue=catalogue,
        limit=limit,
    )
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC),
        "proposal_count": len(proposals),
        "proposals": [proposal.model_dump(mode="json") for proposal in proposals],
        "limitations": [
            "Proposals are private review leads and never alter organization resolution.",
            "Approval requires official source evidence and a reviewed catalogue decision.",
        ],
    }
