"""Closed vocabularies that preserve source and legal distinctions."""

from enum import StrEnum


class ValueOrigin(StrEnum):
    SOURCE_OBSERVED = "source_observed"
    NORMALIZED = "normalized"
    CALCULATED = "calculated"
    MANUALLY_CURATED = "manually_curated"
    DERIVED_CANDIDATE = "derived_candidate"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    INTENTIONALLY_EXCLUDED = "intentionally_excluded"


class ValueState(StrEnum):
    PRESENT = "present"
    ZERO = "zero"
    NULL = "null"
    MISSING = "missing_field"
    NOT_APPLICABLE = "not_applicable"
    SOURCE_OMITTED = "source_omitted"
    UNSUPPORTED = "unsupported"
    FAILED_PARSING = "failed_parsing"
    SUPPRESSED = "suppressed"
    ESTIMATED = "estimated"
    INTENTIONALLY_EXCLUDED = "intentionally_excluded"


class PublicationLevel(StrEnum):
    NATIONAL_AGGREGATE = "national_aggregate"
    STATE_AGGREGATE = "state_aggregate"
    NAMED_NOTIFICATION = "named_notification"
    REGULATOR_REGISTER_ENTRY = "regulator_register_entry"
    REGULATORY_ACTION = "regulatory_action"
    COURT_ACTION = "court_action"
    CYBER_THREAT_CONTEXT = "cyber_threat_context"


class CoverageType(StrEnum):
    COMPLETE_PUBLISHED_DATASET = "complete_published_dataset"
    BOUNDED_HISTORICAL_DATASET = "bounded_historical_dataset"
    ROLLING_PUBLIC_WINDOW = "rolling_public_window"
    SELECTIVE_PUBLIC_NOTIFICATIONS = "selective_public_notifications"
    AGGREGATE_REPORTING_PERIODS = "aggregate_reporting_periods"
    REGULATORY_ACTIONS_ONLY = "regulatory_actions_only"
    UNKNOWN = "unknown"


class EntityRole(StrEnum):
    NOTIFYING_ENTITY = "notifying_entity"
    AFFECTED_ENTITY = "affected_entity"
    COVERED_ENTITY = "covered_entity"
    PUBLIC_SECTOR_AGENCY = "public_sector_agency"
    BUSINESS_ASSOCIATE = "business_associate"
    SERVICE_PROVIDER = "service_provider"
    DATA_OWNER = "data_owner"
    REGULATOR_NAMED_ENTITY = "regulator_named_entity"
    ALLEGED_RESPONDENT = "alleged_respondent"
    DETERMINED_RESPONDENT = "determined_respondent"
    UNKNOWN = "unknown"


class LegalStatus(StrEnum):
    PRELIMINARY_INQUIRY_OPENED = "preliminary_inquiry_opened"
    PRELIMINARY_INQUIRY_COMPLETED = "preliminary_inquiry_completed"
    INVESTIGATION_COMMENCED = "investigation_commenced"
    INVESTIGATION_COMPLETED = "investigation_completed"
    ENFORCEABLE_UNDERTAKING = "enforceable_undertaking"
    DETERMINATION_MADE = "determination_made"
    CIVIL_PROCEEDING_FILED = "civil_proceeding_filed"
    CIVIL_PROCEEDING_ALLEGATION = "civil_proceeding_allegation"
    COURT_JUDGMENT = "court_judgment"
    CIVIL_PENALTY_ORDER = "civil_penalty_order"
    MATTER_CLOSED = "matter_closed"
    OUTCOME_NO_ADVERSE_FINDING = "outcome_no_adverse_finding"
    STATUS_UNKNOWN = "status_unknown"


class Completeness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    ROLLING_WINDOW = "rolling_window"
    SELECTIVE = "selective"
    UNKNOWN = "unknown"


class RelationshipClass(StrEnum):
    LIKELY_SAME_EVENT = "likely_same_publicly_reported_event"
    POSSIBLY_RELATED = "possibly_related_event"
    SHARED_SERVICE_PROVIDER = "shared_service_provider_context"
    SAME_ORGANIZATION_SEPARATE = "same_organization_separate_event"
    RELATED_REGULATORY_ACTION = "related_regulatory_action"
    UNRESOLVED = "unresolved"
