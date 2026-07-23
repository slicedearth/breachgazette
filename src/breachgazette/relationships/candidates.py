"""Generate candidates only from exact entity and compatible source-backed dates."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from breachgazette.contracts import (
    IncidentGroupCandidate,
    NormalizedNotification,
    RelationshipReason,
)
from breachgazette.contracts.enums import RelationshipClass, ValueState
from breachgazette.utils import normalize_organization_name, stable_id


def _date_values(record: NormalizedNotification) -> set[str]:
    return {
        observation.normalized_date.isoformat()
        for observation in record.dates
        if observation.normalized_date is not None
        and observation.meaning
        in {
            "occurrence_start",
            "occurrence_end",
            "awareness_date",
            "regulator_submission_date",
            "public_notification_date",
        }
    }


def generate_candidates(
    notifications: list[NormalizedNotification],
) -> list[IncidentGroupCandidate]:
    candidates: list[IncidentGroupCandidate] = []
    records_by_name: dict[str, list[NormalizedNotification]] = defaultdict(list)
    for record in notifications:
        if (
            record.publication_level == "national_aggregate"
            or record.named_entity.state != ValueState.PRESENT
        ):
            continue
        normalized_name = normalize_organization_name(record.named_entity.source_name)
        if normalized_name:
            records_by_name[normalized_name].append(record)

    for normalized_name in sorted(records_by_name):
        records = sorted(
            records_by_name[normalized_name],
            key=lambda record: (record.source_id, record.source_record_id),
        )
        for left, right in combinations(records, 2):
            if left.source_id == right.source_id:
                continue
            overlapping_dates = sorted(_date_values(left) & _date_values(right))
            if not overlapping_dates:
                continue
            reasons = [
                RelationshipReason(
                    code="exact_canonical_entity",
                    explanation=(
                        "The source names normalize exactly under the conservative resolver."
                    ),
                    evidence=[left.named_entity.source_name, right.named_entity.source_name],
                ),
                RelationshipReason(
                    code="compatible_occurrence_interval",
                    explanation="At least one source-backed date is identical.",
                    evidence=overlapping_dates,
                ),
            ]
            record_ids = sorted([left.source_record_id, right.source_record_id])
            candidates.append(
                IncidentGroupCandidate(
                    candidate_id=stable_id("rel", record_ids, reasons, length=24),
                    relationship_class=RelationshipClass.POSSIBLY_RELATED,
                    record_ids=record_ids,
                    reasons=reasons,
                    limitations=[
                        "This is a relationship candidate, not proof that the records describe "
                        "the same underlying event."
                    ],
                )
            )
    return sorted(candidates, key=lambda candidate: candidate.candidate_id)
