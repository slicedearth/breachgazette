"""Conservative exact and curated-alias organization resolution."""

from __future__ import annotations

from collections import defaultdict

from breachgazette.contracts import (
    NormalizedNotification,
    OrganizationAlias,
    OrganizationIdentity,
    RegulatoryAction,
)
from breachgazette.contracts.enums import EntityRole, ValueState
from breachgazette.entities.catalogue import AliasCatalogue
from breachgazette.utils import normalize_organization_name, stable_id

RESOLVER_VERSION = "1.0"


def resolve_organizations(
    notifications: list[NormalizedNotification],
    regulatory_actions: list[RegulatoryAction],
    *,
    alias_catalogue: AliasCatalogue | None = None,
) -> list[OrganizationIdentity]:
    approved_aliases = alias_catalogue.approved_by_alias if alias_catalogue else {}
    grouped: dict[str, list[OrganizationAlias]] = defaultdict(list)
    canonical_names: dict[str, str] = {}

    def add_alias(*, source_id: str, source_name: str, role: EntityRole) -> None:
        normalized = normalize_organization_name(source_name)
        reviewed_decision = approved_aliases.get(normalized)
        key = (
            normalize_organization_name(reviewed_decision.canonical_name)
            if reviewed_decision
            else normalized
        )
        method = "curated_alias" if reviewed_decision else "exact_normalized"
        if reviewed_decision:
            canonical_names[key] = reviewed_decision.canonical_name
        else:
            canonical_names.setdefault(key, source_name)
        grouped[key].append(
            OrganizationAlias(
                source_id=source_id,
                source_name=source_name,
                normalized_name=normalized,
                role=role,
                match_method=method,
                confidence_class="reviewed" if reviewed_decision else "exact",
                supporting_evidence=(
                    ["Reviewed alias decision applied"]
                    if reviewed_decision
                    else ["Exact normalized source name"]
                ),
                resolver_version=RESOLVER_VERSION,
            )
        )

    for notification in notifications:
        if notification.named_entity.state != ValueState.PRESENT:
            continue
        add_alias(
            source_id=notification.source_id,
            source_name=notification.named_entity.source_name,
            role=notification.named_entity.role,
        )
    for action in regulatory_actions:
        if action.entity.state != ValueState.PRESENT:
            continue
        add_alias(
            source_id=action.source_id,
            source_name=action.entity.source_name,
            role=action.entity.role,
        )

    identities: list[OrganizationIdentity] = []
    for key in sorted(grouped):
        aliases = sorted(
            grouped[key],
            key=lambda item: (item.source_name.casefold(), item.source_id, item.role),
        )
        identities.append(
            OrganizationIdentity(
                organization_id=stable_id("org", key, length=16),
                canonical_name=canonical_names[key],
                aliases=aliases,
            )
        )
    return identities
