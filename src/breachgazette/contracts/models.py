"""Pydantic v2 contracts for heterogeneous official breach publications."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from breachgazette.contracts.enums import (
    Completeness,
    CoverageType,
    EntityRole,
    LegalStatus,
    PublicationLevel,
    RelationshipClass,
    ValueOrigin,
    ValueState,
)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class ObservedValue(ContractModel):
    value: str | int | float | bool | None = None
    origin: ValueOrigin
    state: ValueState = ValueState.PRESENT
    source_label: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def classify_zero_and_null(self) -> ObservedValue:
        if self.value is None and self.state == ValueState.PRESENT:
            self.state = ValueState.NULL
        elif self.value == 0 and self.state == ValueState.PRESENT:
            self.state = ValueState.ZERO
        return self


class SourcePolicy(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    rights_reviewed_on: date
    source_id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=200)
    country: str = Field(min_length=2, max_length=100)
    jurisdiction: str = Field(min_length=2, max_length=100)
    regulator: str = Field(min_length=2, max_length=200)
    reporting_scheme: str = Field(min_length=2, max_length=300)
    publication_level: PublicationLevel
    unit_of_observation: str = Field(min_length=2, max_length=500)
    source_threshold: str = Field(min_length=2, max_length=800)
    source_population: str = Field(min_length=2, max_length=800)
    public_window: str = Field(min_length=2, max_length=800)
    coverage_type: CoverageType
    aggregate: bool
    organizations_named: bool
    records_may_be_amended: bool
    records_may_disappear: bool
    counts_may_be_estimates: bool
    duplicate_notifications_may_be_consolidated: bool
    notifier_may_differ_from_affected_entity: bool
    source_licence: str = Field(min_length=2, max_length=1000)
    attribution: str = Field(min_length=2, max_length=500)
    redistribution_decision: Literal["approved", "approved_with_conditions", "deferred"]
    correction_process: str = Field(min_length=2, max_length=1000)
    source_url: HttpUrl
    implemented: bool = True
    limitations: list[str] = Field(min_length=1, max_length=20)


class SourceManifest(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    source_id: str
    adapter_version: str
    expected_schema: list[str]
    fixed_urls: list[HttpUrl]
    max_rows: int = Field(ge=1, le=100_000)
    max_pages: int = Field(ge=1, le=1_000)
    max_response_bytes: int = Field(ge=1_024, le=100_000_000)


class SourceSnapshot(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    source_id: str
    retrieved_at: datetime
    completed_at: datetime
    revision: str = Field(min_length=1, max_length=300)
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    completeness: Completeness
    records_discovered: int = Field(ge=0)
    records_accepted: int = Field(ge=0)
    records_rejected: int = Field(ge=0)
    bounded_limit: int = Field(ge=1)
    source_updated_at: datetime | None = None
    last_successful_complete_update: datetime | None = None
    latest_attempted_update: datetime
    stale: bool = False
    notes: list[str] = Field(default_factory=list, max_length=20)


class RecordProvenance(ContractModel):
    source_id: str
    source_record_id: str = Field(min_length=1, max_length=300)
    source_url: HttpUrl
    source_revision: str = Field(min_length=1, max_length=300)
    source_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_completeness: Completeness
    source_retrieval_time: datetime
    local_first_observed_time: datetime
    local_last_observed_time: datetime
    parser_version: str
    normalization_version: str
    limitations: list[str] = Field(default_factory=list, max_length=20)


class SourceAggregateRecord(RecordProvenance):
    record_type: Literal["aggregate"] = "aggregate"
    regulator: str
    reporting_scheme: str
    publication_level: PublicationLevel
    reporting_period_start: date
    reporting_period_end: date
    dimension: str
    category: str
    parent_category: str | None = None
    value: ObservedValue
    unit: str
    population_scope: str
    denominator: int | None = Field(default=None, ge=0)
    rounding_state: ValueState = ValueState.PRESENT
    source_notes: list[str] = Field(default_factory=list, max_length=10)


class DateObservation(ContractModel):
    meaning: Literal[
        "occurrence_start",
        "occurrence_end",
        "discovery_date",
        "awareness_date",
        "consumer_notification_date",
        "regulator_submission_date",
        "public_notification_date",
        "regulator_publication_date",
        "reporting_period_start",
        "reporting_period_end",
        "source_update_date",
    ]
    raw_value: str | None = Field(default=None, max_length=500)
    normalized_date: date | None = None
    origin: ValueOrigin
    state: ValueState


class PopulationObservation(ContractModel):
    count: int | None = Field(default=None, ge=0)
    scope: str = Field(min_length=1, max_length=300)
    estimated: bool
    origin: ValueOrigin
    state: ValueState


class InformationCategory(ContractModel):
    source_label: str
    normalized_label: str
    origin: ValueOrigin


class BreachCause(ContractModel):
    source_label: str | None = None
    normalized_label: str | None = None
    subtype: str | None = None
    origin: ValueOrigin
    state: ValueState


class OrganizationRole(ContractModel):
    source_name: str = Field(min_length=1, max_length=500)
    normalized_name: str = Field(min_length=1, max_length=500)
    role: EntityRole
    origin: ValueOrigin
    state: ValueState = ValueState.PRESENT


class SourceNotificationRecord(RecordProvenance):
    record_type: Literal["notification"] = "notification"
    regulator: str
    jurisdiction: str
    reporting_scheme: str
    publication_level: PublicationLevel
    coverage_type: CoverageType
    named_entity: OrganizationRole
    dates: list[DateObservation]
    affected_population: PopulationObservation | None = None
    information_categories: list[InformationCategory] = Field(default_factory=list)
    breach_cause: BreachCause | None = None
    industry: str | None = Field(default=None, max_length=200)
    register_window_state: Literal["current", "expired", "not_applicable"] = "not_applicable"
    source_detail_url: HttpUrl | None = None


class SourceRegulatoryRecord(RecordProvenance):
    record_type: Literal["regulatory"] = "regulatory"
    regulator: str
    matter_id: str
    entity: OrganizationRole
    legal_status: LegalStatus
    source_title: str
    source_publication_date: date
    source_reported_event_date: date
    status_wording: str
    summary: str = Field(min_length=1, max_length=1_200)
    previous_related_event: str | None = None
    allegation: bool = False
    finding: bool = False

    @model_validator(mode="after")
    def legal_status_is_explicit(self) -> SourceRegulatoryRecord:
        if self.legal_status == LegalStatus.STATUS_UNKNOWN:
            raise ValueError("ambiguous regulatory status cannot be published")
        if self.allegation and self.finding:
            raise ValueError("one regulatory action cannot be both allegation and finding")
        if (
            self.legal_status
            in {
                LegalStatus.CIVIL_PROCEEDING_FILED,
                LegalStatus.CIVIL_PROCEEDING_ALLEGATION,
            }
            and self.finding
        ):
            raise ValueError("a civil filing cannot be rendered as a finding")
        return self


class NormalizedAggregateMetric(SourceAggregateRecord):
    pass


class NormalizedNotification(SourceNotificationRecord):
    canonical_organization_id: str | None = None


class RegulatoryAction(SourceRegulatoryRecord):
    canonical_organization_id: str | None = None


class OrganizationAlias(ContractModel):
    source_id: str
    source_name: str
    normalized_name: str
    role: EntityRole
    match_method: Literal["exact_normalized", "curated_alias", "stable_source_identifier"]
    confidence_class: Literal["exact", "reviewed"]
    supporting_evidence: list[str]
    resolver_version: str
    review_note: str | None = None


class OrganizationIdentity(ContractModel):
    organization_id: str = Field(pattern=r"^org_[0-9a-f]{16}$")
    canonical_name: str
    aliases: list[OrganizationAlias]


class AliasReviewDecision(ContractModel):
    decision_id: str = Field(pattern=r"^alias_[0-9a-f]{16}$")
    alias_name: str = Field(min_length=2, max_length=500)
    canonical_name: str = Field(min_length=2, max_length=500)
    status: Literal["approved", "rejected"]
    source_ids: list[str] = Field(min_length=1, max_length=10)
    evidence: list[str] = Field(min_length=1, max_length=10)
    reviewed_on: date
    review_note: str = Field(min_length=2, max_length=500)


class AliasProposal(ContractModel):
    proposal_id: str = Field(pattern=r"^alias_proposal_[0-9a-f]{16}$")
    left_name: str = Field(min_length=2, max_length=500)
    right_name: str = Field(min_length=2, max_length=500)
    left_normalized_name: str = Field(min_length=2, max_length=500)
    right_normalized_name: str = Field(min_length=2, max_length=500)
    source_ids: list[str] = Field(min_length=2, max_length=10)
    similarity_score: float = Field(ge=0, le=1)
    reasons: list[str] = Field(min_length=1, max_length=10)


class RelationshipReason(ContractModel):
    code: Literal[
        "exact_canonical_entity",
        "compatible_occurrence_interval",
        "compatible_awareness_date",
        "compatible_affected_scale",
        "compatible_source_cause",
        "shared_service_provider_context",
        "explicit_source_cross_reference",
        "exact_public_incident_identifier",
    ]
    explanation: str
    evidence: list[str]


class IncidentGroupCandidate(ContractModel):
    candidate_id: str = Field(pattern=r"^rel_[0-9a-f]{24}$")
    relationship_class: RelationshipClass
    record_ids: list[str] = Field(min_length=2, max_length=10)
    reasons: list[RelationshipReason] = Field(min_length=1, max_length=10)
    origin: Literal[ValueOrigin.DERIVED_CANDIDATE] = ValueOrigin.DERIVED_CANDIDATE
    reviewed: bool = False
    review_status: Literal["confirmed_related", "rejected", "unresolved"] | None = None
    reviewed_on: date | None = None
    review_note: str | None = Field(default=None, max_length=500)
    review_evidence: list[str] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(min_length=1)


class RelationshipReviewDecision(ContractModel):
    decision_id: str = Field(pattern=r"^relationship_[0-9a-f]{16}$")
    candidate_id: str = Field(pattern=r"^rel_[0-9a-f]{24}$")
    status: Literal["confirmed_related", "rejected", "unresolved"]
    record_ids: list[str] = Field(min_length=2, max_length=10)
    evidence: list[str] = Field(min_length=1, max_length=10)
    reviewed_on: date
    review_note: str = Field(min_length=2, max_length=500)
    decision_version: Literal["1.0"] = "1.0"


class IncidentGroup(ContractModel):
    group_id: str
    record_ids: list[str] = Field(min_length=2)
    relationship_class: RelationshipClass
    reasons: list[RelationshipReason]
    reviewed_at: datetime
    review_note: str


class NotificationVersion(ContractModel):
    version_id: str
    record: NormalizedNotification
    observed_at: datetime


class NotificationChange(ContractModel):
    event_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: Literal["1.0"] = "1.0"
    source_id: str
    record_id: str
    event_type: str
    before_value: Any = None
    after_value: Any = None
    reason: str
    previous_snapshot: str | None = None
    current_snapshot: str
    source_completeness: Completeness
    detector_version: str
    first_observed_time: datetime
    limitations: list[str] = Field(default_factory=list)


class RegulatoryStatusChange(NotificationChange):
    previous_status: LegalStatus | None = None
    current_status: LegalStatus


class PublicationRecord(ContractModel):
    record_id: str
    record_type: Literal["aggregate", "notification", "regulatory", "relationship"]
    source_id: str
    payload: dict[str, Any]


class PublicationManifest(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    dataset_class: Literal["real_source_data", "test_fixture"]
    record_counts: dict[str, int]
    source_snapshots: list[SourceSnapshot]
    publication_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    publication_checksum_algorithm: Literal["sha256_canonical_json_v1"]
    publication_checksum_scope: Literal[
        "publication_summary_and_search_partition_digests"
    ]
    max_public_records: int = Field(ge=1)
    max_public_corrections: int = Field(ge=1)
    limitations: list[str]


class QualityFinding(ContractModel):
    detector_id: str
    field: str
    reason: str
    redacted_fingerprint: str
    record_identity: str
    outcome: Literal["rejected", "warning", "accepted"]


class QualityReport(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    passed: bool
    dataset_class: Literal["real_source_data", "test_fixture"]
    source_health: dict[str, str]
    checks: dict[str, bool]
    findings: list[QualityFinding] = Field(default_factory=list)
    record_counts: dict[str, int]
    limitations: list[str]


class SourceMonitoringPolicy(ContractModel):
    source_id: str = Field(pattern=r"^[a-z0-9_]+$")
    stale_after_hours: int = Field(ge=1, le=8_760)
    minimum_records: int = Field(ge=1)
    minimum_retained_fraction: float = Field(gt=0, le=1)
    maximum_growth_factor: float = Field(ge=1, le=10)


class MonitoringCatalogue(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    schedule_utc: str = Field(min_length=9, max_length=100)
    sources: dict[str, SourceMonitoringPolicy]


class SourceHealthEntry(ContractModel):
    source_id: str
    status: Literal[
        "healthy",
        "missing",
        "stale",
        "failed_update",
        "incomplete_update",
        "record_count_below_floor",
    ]
    record_count: int = Field(ge=0)
    minimum_records: int = Field(ge=1)
    completeness: Completeness | None = None
    snapshot_checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    snapshot_age_hours: float | None = Field(default=None, ge=0)
    stale_after_hours: int = Field(ge=1)
    latest_attempted_update: datetime | None = None
    last_successful_update: datetime | None = None
    checkpoint_status: Literal["missing", "in_progress", "complete", "failed"]
    reasons: list[str] = Field(default_factory=list, max_length=10)


class SourceHealthReport(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    dataset_class: Literal["real_source_data", "test_fixture", "unknown"]
    passed: bool
    schedule_utc: str
    sources: list[SourceHealthEntry]
    limitations: list[str] = Field(min_length=1, max_length=10)


class UpdateCheckpoint(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    source_id: str
    attempted_at: datetime
    completed_at: datetime | None = None
    status: Literal["in_progress", "complete", "failed"]
    snapshot_checksum: str | None = None
    detail: str = Field(max_length=500)
