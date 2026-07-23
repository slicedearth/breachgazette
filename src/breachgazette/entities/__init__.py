"""Deterministic organization identity resolution."""

from breachgazette.entities.catalogue import (
    AliasCatalogue,
    alias_decision_id,
    load_alias_catalogue,
)
from breachgazette.entities.proposals import build_alias_proposal_report, propose_alias_reviews
from breachgazette.entities.resolver import resolve_organizations

__all__ = [
    "AliasCatalogue",
    "alias_decision_id",
    "build_alias_proposal_report",
    "load_alias_catalogue",
    "propose_alias_reviews",
    "resolve_organizations",
]
