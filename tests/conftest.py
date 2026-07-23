from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from breachgazette.contracts import (
    DateObservation,
    NormalizedNotification,
    OrganizationRole,
)
from breachgazette.contracts.enums import (
    Completeness,
    CoverageType,
    EntityRole,
    PublicationLevel,
    ValueOrigin,
    ValueState,
)
from breachgazette.utils import normalize_organization_name


@pytest.fixture
def observed_at() -> datetime:
    return datetime(2026, 1, 15, 10, 30, tzinfo=UTC)


@pytest.fixture
def notification_factory(observed_at: datetime):
    def build(
        *,
        source_id: str = "washington",
        record_id: str = "record-1",
        name: str = "Example Health Limited",
        role: EntityRole = EntityRole.NOTIFYING_ENTITY,
        observed_date: date = date(2025, 12, 1),
        **changes: Any,
    ) -> NormalizedNotification:
        values: dict[str, Any] = {
            "source_id": source_id,
            "source_record_id": record_id,
            "source_url": "https://example.gov/source",
            "source_revision": "revision-1",
            "source_checksum": "a" * 64,
            "source_completeness": Completeness.COMPLETE,
            "source_retrieval_time": observed_at,
            "local_first_observed_time": observed_at,
            "local_last_observed_time": observed_at,
            "parser_version": "1.0",
            "normalization_version": "1.0",
            "limitations": ["Test-only synthetic record."],
            "regulator": "Example Regulator",
            "jurisdiction": "Example",
            "reporting_scheme": "Example notification scheme",
            "publication_level": PublicationLevel.NAMED_NOTIFICATION,
            "coverage_type": CoverageType.COMPLETE_PUBLISHED_DATASET,
            "named_entity": OrganizationRole(
                source_name=name,
                normalized_name=normalize_organization_name(name),
                role=role,
                origin=ValueOrigin.SOURCE_OBSERVED,
            ),
            "dates": [
                DateObservation(
                    meaning="occurrence_start",
                    raw_value=observed_date.isoformat(),
                    normalized_date=observed_date,
                    origin=ValueOrigin.SOURCE_OBSERVED,
                    state=ValueState.PRESENT,
                )
            ],
        }
        values.update(changes)
        return NormalizedNotification.model_validate(values)

    return build
