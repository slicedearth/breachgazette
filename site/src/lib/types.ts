export type DateObservation = {
  meaning: string;
  raw_value: string | null;
  normalized_date: string | null;
  origin: string;
  state: string;
};

export type Notification = {
  source_id: string;
  source_record_id: string;
  source_url: string;
  source_revision: string;
  source_completeness: string;
  source_retrieval_time: string;
  local_first_observed_time: string;
  local_last_observed_time: string;
  regulator: string;
  jurisdiction: string;
  reporting_scheme: string;
  publication_level: string;
  coverage_type: string;
  named_entity: {
    source_name: string;
    normalized_name: string;
    role: string;
    state: string;
  };
  dates: DateObservation[];
  affected_population?: {
    count: number | null;
    scope: string;
    estimated: boolean;
    state: string;
  } | null;
  information_categories: Array<{ source_label: string; normalized_label: string }>;
  breach_cause?: { source_label: string | null; normalized_label: string | null } | null;
  register_window_state: string;
  source_detail_url?: string | null;
  canonical_organization_id?: string | null;
  has_detail_page?: boolean;
  limitations: string[];
};

export type SearchFacets = {
  jurisdictions: string[];
  regulators: string[];
  sources: string[];
  years: string[];
  causes: string[];
  information_categories: string[];
  population_bands: string[];
  roles: string[];
  publication_levels: string[];
};

export type SearchPartitionMetadata = SearchFacets & {
  id: string;
  count: number;
  bytes: number;
  sha256: string;
  query_bloom: string;
};

export type SearchManifest = {
  schema_version: string;
  generated_at: string;
  record_count: number;
  partition_size: number;
  partition_max_bytes: number;
  query_routing: {
    algorithm: "normalized_trigram_bloom";
    encoding: "hex";
    bits: number;
    hashes: number;
    minimum_query_length: number;
  };
  facets: SearchFacets;
  facet_counts: {
    [Facet in keyof SearchFacets]: Record<string, number>;
  };
  partitions: SearchPartitionMetadata[];
};

export type SearchPartition = {
  schema_version: string;
  partition_id: string;
  records: Notification[];
};

export type Aggregate = {
  source_id: string;
  source_record_id: string;
  regulator: string;
  reporting_scheme: string;
  reporting_period_start: string;
  reporting_period_end: string;
  dimension: string;
  category: string;
  parent_category: string | null;
  value: { value: string | number | null; state: string; source_label: string | null };
  unit: string;
  population_scope: string;
  source_url: string;
  source_revision: string;
  source_notes: string[];
};

export type RegulatoryAction = {
  source_id: string;
  source_record_id: string;
  source_url: string;
  source_revision: string;
  regulator: string;
  matter_id: string;
  entity: { source_name: string; normalized_name: string; role: string };
  legal_status: string;
  source_title: string;
  source_publication_date: string;
  source_reported_event_date: string;
  status_wording: string;
  summary: string;
  allegation: boolean;
  finding: boolean;
  canonical_organization_id?: string | null;
  limitations: string[];
};

export type Organization = {
  organization_id: string;
  canonical_name: string;
  aliases: Array<{
    source_id: string;
    source_name: string;
    role: string;
    match_method: string;
    confidence_class?: string;
    supporting_evidence: string[];
    resolver_version?: string;
  }>;
};

export type Relationship = {
  candidate_id: string;
  relationship_class: string;
  record_ids: string[];
  reasons: Array<{ code: string; explanation: string; evidence: string[] }>;
  reviewed: boolean;
  review_status?: "confirmed_related" | "unresolved" | null;
  reviewed_on?: string | null;
  limitations: string[];
};

export type CorrectionEvent = {
  event_id: string;
  schema_version: string;
  source_id: string;
  record_id: string;
  event_type: string;
  before_value: unknown;
  after_value: unknown;
  reason: string;
  previous_snapshot: string | null;
  current_snapshot: string;
  source_completeness: string;
  detector_version: string;
  first_observed_time: string;
  limitations: string[];
};

export type SourcePolicy = {
  source_id: string;
  rights_reviewed_on: string;
  name: string;
  country: string;
  jurisdiction: string;
  regulator: string;
  reporting_scheme: string;
  publication_level: string;
  unit_of_observation: string;
  source_threshold: string;
  source_population: string;
  public_window: string;
  coverage_type: string;
  source_licence: string;
  attribution: string;
  redistribution_decision: string;
  correction_process: string;
  source_url: string;
  implemented: boolean;
  limitations: string[];
};

export type SourceSnapshot = {
  schema_version: string;
  source_id: string;
  retrieved_at: string;
  completed_at: string;
  revision: string;
  checksum_sha256: string;
  completeness: string;
  records_discovered: number;
  records_accepted: number;
  records_rejected: number;
  bounded_limit: number;
  source_updated_at: string | null;
  last_successful_complete_update: string | null;
  latest_attempted_update: string;
  stale: boolean;
  notes: string[];
};

export type Publication = {
  schema_version: string;
  generated_at: string;
  tagline: string;
  disclaimer: string;
  stats: Record<string, number>;
  detail_notifications: Notification[];
  aggregates: Aggregate[];
  regulatory_actions: RegulatoryAction[];
  detail_organizations: Organization[];
  relationships: Relationship[];
  corrections: CorrectionEvent[];
  policies: Record<string, SourcePolicy>;
  snapshots: SourceSnapshot[];
  quality: {
    passed: boolean;
    dataset_class: string;
    checks: Record<string, boolean>;
    source_health: Record<string, string>;
    findings: string[];
    limitations: string[];
  };
  source_health: {
    passed: boolean;
    schedule_utc: string;
    generated_at: string;
    sources: Array<{
      source_id: string;
      status: string;
      record_count: number;
      minimum_records: number;
      completeness: string | null;
      snapshot_checksum: string | null;
      snapshot_age_hours: number | null;
      stale_after_hours: number;
      latest_attempted_update: string | null;
      last_successful_update: string | null;
      checkpoint_status: string;
      reasons: string[];
    }>;
  };
  manifest: {
    dataset_class: string;
    generated_at: string;
    record_counts: Record<string, number>;
    source_snapshots: SourceSnapshot[];
    publication_checksum: string;
    publication_checksum_algorithm: "sha256_canonical_json_v1";
    publication_checksum_scope: "publication_summary_and_search_partition_digests";
    max_public_records: number;
    max_public_corrections: number;
    limitations: string[];
  };
  deferred_sources: SourcePolicy[];
};
