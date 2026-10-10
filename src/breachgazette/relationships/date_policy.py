"""Date compatibility helpers with an explicit, unchanged legacy default."""

from __future__ import annotations

from typing import Literal

from breachgazette.contracts import NormalizedNotification

DatePolicy = Literal["calendar_date_v1", "same_meaning_v1"]
MEANINGS = frozenset(
    {
        "occurrence_start",
        "occurrence_end",
        "awareness_date",
        "regulator_submission_date",
        "public_notification_date",
    }
)


def date_keys(
    record: NormalizedNotification, *, policy: DatePolicy = "calendar_date_v1"
) -> set[str]:
    if policy not in {"calendar_date_v1", "same_meaning_v1"}:
        raise ValueError("unsupported relationship date policy")
    return {
        (f"{observation.meaning}:" if policy == "same_meaning_v1" else "")
        + observation.normalized_date.isoformat()
        for observation in record.dates
        if observation.normalized_date is not None and observation.meaning in MEANINGS
    }
