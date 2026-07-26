# Data dictionary

| Contract | Meaning |
| --- | --- |
| `SourcePolicy` | Reviewed semantics, dated rights assessment, limits, and correction boundary |
| `SourceSnapshot` | One bounded retrieval attempt and completeness state |
| `SourceAggregateRecord` | One source-published aggregate cell |
| `SourceAnonymizedNotificationRecord` | One notification row with no organization identity and explicit source date precision |
| `SourceNotificationRecord` | One named source notification row |
| `SourceRegulatoryRecord` | One reviewed legal-status event |
| `NormalizedNotification` | Notification plus publication-time organization ID |
| `OrganizationIdentity` | Exact or reviewed organization aliases |
| `AliasReviewDecision` | Approved or rejected evidence-bearing alias review |
| `AliasProposal` | Private non-operative lead for human alias review |
| `IncidentGroupCandidate` | Explainable, unconfirmed cross-source relationship |
| `RelationshipReviewDecision` | Confirmed-related, rejected, or unresolved relationship review |
| `NotificationChange` | Immutable snapshot comparison event |
| `SourceMonitoringPolicy` | Freshness and source-count drift thresholds |
| `SourceHealthReport` | Non-sensitive update and snapshot health states |
| `QualityReport` | Machine-readable publication checks and source health |
| `PublicationManifest` | Data class, counts, checksums, snapshots, and limits |
| `RetentionPolicy` | Managed state directories, report retention, and byte bounds |

Alias proposals and review-decision catalogues are private operational state.
The public repository contains only their contracts and empty synthetic
catalogue fixtures.

The browser-search manifest lists global facets, bounded partition metadata,
and a deterministic hex-encoded trigram Bloom value for each partition. Bloom
matches can create extra loads but not omit a true match. Each source/year
partition contains at most 250 public notification records. CSV export is
generated locally from every matching loaded partition, not only the 50 rows
displayed.

All provenance-bearing records include source ID, record ID, safe official URL,
revision, SHA-256 checksum, source completeness, retrieval time, first and last
local observation, parser and normalization versions, and limitations.
Date observations also retain source precision, including month-level dates.
The implemented CNIL and UK ICO paths validate anonymous rows transiently and
store only grouped `SourceAggregateRecord` metrics. The UK path first groups
rows by source report reference and excludes unresolved reporting-period
conflicts, reducing privacy and repository-size risk.

The Netherlands AP path publishes five attributed annual aggregate values.
The annual notification total, cyberattack-cause count, and account-takeover
count remain distinct source-defined dimensions. They are not an additive
breakdown, and their records contain no organization identities.
