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
| `IncidentGroupCandidate` | Explainable, unconfirmed cross-source relationship |
| `NotificationChange` | Immutable snapshot comparison event |
| `QualityReport` | Machine-readable publication checks and source health |
| `PublicationManifest` | Data class, counts, checksums, snapshots, and limits |

All provenance-bearing records include source ID, record ID, safe official URL,
revision, SHA-256 checksum, source completeness, retrieval time, first and last
local observation, parser and normalization versions, and limitations.
