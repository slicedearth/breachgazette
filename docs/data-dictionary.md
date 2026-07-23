# Data dictionary

| Contract | Meaning |
| --- | --- |
| `SourcePolicy` | Reviewed semantics, rights, limits, and correction boundary |
| `SourceSnapshot` | One bounded retrieval attempt and completeness state |
| `SourceAggregateRecord` | One source-published aggregate cell |
| `SourceNotificationRecord` | One named source notification row |
| `SourceRegulatoryRecord` | One reviewed legal-status event |
| `NormalizedNotification` | Notification plus publication-time organization ID |
| `OrganizationIdentity` | Exact or reviewed organization aliases |
| `AliasReviewDecision` | Approved or rejected evidence-bearing alias review |
| `AliasProposal` | Private non-operative lead for human alias review |
| `IncidentGroupCandidate` | Explainable, unconfirmed cross-source relationship |
| `NotificationChange` | Immutable snapshot comparison event |
| `SourceMonitoringPolicy` | Freshness and source-count drift thresholds |
| `SourceHealthReport` | Non-sensitive update and snapshot health states |
| `QualityReport` | Machine-readable publication checks and source health |
| `PublicationManifest` | Data class, counts, checksums, snapshots, and limits |

The browser-search manifest lists global facets and bounded partition metadata.
Each source/year partition contains at most 250 public notification records and
is fetched only when a filter can use it.

All provenance-bearing records include source ID, record ID, safe official URL,
revision, SHA-256 checksum, source completeness, retrieval time, first and last
local observation, parser and normalization versions, and limitations.
