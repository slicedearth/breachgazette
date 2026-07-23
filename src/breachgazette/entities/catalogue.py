"""Reviewed organization-alias decisions with deterministic validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from breachgazette.contracts import AliasReviewDecision
from breachgazette.policies import load_source_policies
from breachgazette.utils import normalize_organization_name, stable_id


@dataclass(frozen=True)
class AliasCatalogue:
    decisions: tuple[AliasReviewDecision, ...]

    @property
    def approved_by_alias(self) -> dict[str, AliasReviewDecision]:
        return {
            normalize_organization_name(decision.alias_name): decision
            for decision in self.decisions
            if decision.status == "approved"
        }

    @property
    def decided_pairs(self) -> set[frozenset[str]]:
        return {
            frozenset(
                {
                    normalize_organization_name(decision.alias_name),
                    normalize_organization_name(decision.canonical_name),
                }
            )
            for decision in self.decisions
        }


def alias_decision_id(alias_name: str, canonical_name: str) -> str:
    return stable_id(
        "alias",
        normalize_organization_name(alias_name),
        normalize_organization_name(canonical_name),
        length=16,
    )


def load_alias_catalogue(path: Path) -> AliasCatalogue:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "2.0":
        raise ValueError("organization alias catalogue must use schema_version 2.0")
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise ValueError("organization alias catalogue decisions must be a list")
    decisions = tuple(AliasReviewDecision.model_validate(item) for item in raw_decisions)
    known_sources = set(load_source_policies())
    seen_aliases: set[str] = set()
    approved_aliases: set[str] = set()
    approved_canonicals: set[str] = set()
    canonical_labels: dict[str, str] = {}
    for decision in decisions:
        alias_key = normalize_organization_name(decision.alias_name)
        canonical_key = normalize_organization_name(decision.canonical_name)
        if not alias_key or not canonical_key or alias_key == canonical_key:
            raise ValueError("alias decisions must map two different non-empty normalized names")
        if decision.decision_id != alias_decision_id(
            decision.alias_name,
            decision.canonical_name,
        ):
            raise ValueError(f"alias decision has a non-deterministic id: {decision.decision_id}")
        if alias_key in seen_aliases:
            raise ValueError(f"alias name has more than one decision: {decision.alias_name}")
        if decision.source_ids != sorted(set(decision.source_ids)):
            raise ValueError("alias decision source_ids must be unique and sorted")
        if unknown := set(decision.source_ids) - known_sources:
            raise ValueError(
                f"alias decision references unknown sources: {', '.join(sorted(unknown))}"
            )
        if decision.reviewed_on > date.today():
            raise ValueError("alias decisions cannot be future-dated")
        seen_aliases.add(alias_key)
        if decision.status == "approved":
            approved_aliases.add(alias_key)
            approved_canonicals.add(canonical_key)
            prior_label = canonical_labels.setdefault(canonical_key, decision.canonical_name)
            if prior_label != decision.canonical_name:
                raise ValueError("one canonical key must use one reviewed display name")
    if approved_aliases & approved_canonicals:
        raise ValueError("approved alias chains and cycles are not permitted")
    return AliasCatalogue(decisions=decisions)
