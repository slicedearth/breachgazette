# ADR 0002: Separate aggregate, notification, and regulatory records

## Decision

Use distinct closed contracts and public views for aggregate statistics,
named notifications, and legal-status events.

## Consequences

Aggregate cells cannot acquire organization identities or enter incident
grouping. Proceedings cannot silently inherit findings. Cross-source analysis
must display compatible source semantics.
