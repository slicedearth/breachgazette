"""Conservative handling for source-observed date conflicts."""

from __future__ import annotations

from breachgazette.contracts import SourceNotificationRecord
from breachgazette.contracts.enums import ValueState

TEMPORAL_CONFLICT_LIMITATION = (
    "A source-observed occurrence date post-dates the regulator submission date. "
    "The raw source value is retained, but the conflicting date is excluded from "
    "normalized date sorting, filtering, feeds, and relationship matching."
)


def exclude_temporal_conflicts(record: SourceNotificationRecord) -> int:
    """Exclude impossible source dates from normalized uses without losing raw text."""
    if record.source_id != "california":
        return 0
    submission_dates = [
        observation.normalized_date
        for observation in record.dates
        if observation.meaning == "regulator_submission_date"
        and observation.normalized_date is not None
    ]
    if not submission_dates:
        return 0
    first_submission = min(submission_dates)
    conflicts = 0
    for observation in record.dates:
        if (
            observation.meaning in {"occurrence_start", "occurrence_end"}
            and observation.normalized_date is not None
            and observation.normalized_date > first_submission
        ):
            observation.normalized_date = None
            observation.state = ValueState.SOURCE_CONFLICT
            conflicts += 1
    if conflicts and TEMPORAL_CONFLICT_LIMITATION not in record.limitations:
        record.limitations.append(TEMPORAL_CONFLICT_LIMITATION)
    return conflicts
