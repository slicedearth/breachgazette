"""Reviewed relationship decisions kept separate from candidate generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from breachgazette.contracts import IncidentGroupCandidate, RelationshipReviewDecision
from breachgazette.contracts.enums import RelationshipClass
from breachgazette.utils import stable_id


def relationship_decision_id(candidate_id: str, record_ids: list[str]) -> str:
    return stable_id("relationship", candidate_id, sorted(record_ids), length=16)


@dataclass(frozen=True)
class RelationshipCatalogue:
    decisions: tuple[RelationshipReviewDecision, ...]

    @property
    def by_candidate(self) -> dict[str, RelationshipReviewDecision]:
        return {decision.candidate_id: decision for decision in self.decisions}


def load_relationship_catalogue(path: Path) -> RelationshipCatalogue:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError("relationship catalogue must use schema_version 1.0")
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise ValueError("relationship catalogue decisions must be a list")
    decisions = tuple(RelationshipReviewDecision.model_validate(item) for item in raw_decisions)
    seen: set[str] = set()
    today = date.today()
    for decision in decisions:
        if decision.candidate_id in seen:
            raise ValueError(f"duplicate relationship decision: {decision.candidate_id}")
        seen.add(decision.candidate_id)
        if decision.record_ids != sorted(set(decision.record_ids)):
            raise ValueError("relationship decision record IDs must be unique and sorted")
        if decision.decision_id != relationship_decision_id(
            decision.candidate_id, decision.record_ids
        ):
            raise ValueError(f"relationship decision ID is not stable: {decision.candidate_id}")
        if decision.reviewed_on > today:
            raise ValueError("relationship decision date cannot be in the future")
    return RelationshipCatalogue(decisions=decisions)


def apply_relationship_decisions(
    candidates: list[IncidentGroupCandidate],
    *,
    catalogue: RelationshipCatalogue,
) -> tuple[list[IncidentGroupCandidate], list[RelationshipReviewDecision]]:
    candidates_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    published: list[IncidentGroupCandidate] = []
    for candidate in candidates:
        decision = catalogue.by_candidate.get(candidate.candidate_id)
        if decision is None:
            published.append(candidate)
            continue
        if decision.record_ids != candidate.record_ids:
            raise ValueError(
                f"relationship decision record IDs changed: {candidate.candidate_id}"
            )
        if decision.status == "rejected":
            continue
        candidate.reviewed = True
        candidate.review_status = decision.status
        candidate.reviewed_on = decision.reviewed_on
        candidate.review_note = decision.review_note
        candidate.review_evidence = decision.evidence
        candidate.relationship_class = (
            RelationshipClass.LIKELY_SAME_EVENT
            if decision.status == "confirmed_related"
            else RelationshipClass.UNRESOLVED
        )
        candidate.limitations = [
            (
                "This reviewed decision links public source records; it does not merge their "
                "provenance, legal meaning, or source-defined roles."
            )
        ]
        published.append(candidate)
    missing = sorted(set(catalogue.by_candidate) - set(candidates_by_id))
    if missing:
        raise ValueError(
            f"relationship decisions reference missing candidates: {', '.join(missing)}"
        )
    return (
        sorted(published, key=lambda candidate: candidate.candidate_id),
        sorted(catalogue.decisions, key=lambda decision: decision.decision_id),
    )
