# ADR 0003: Require exact identity evidence

## Decision

Resolve organization names through deterministic exact normalization and
reviewed aliases only. Generate relationship candidates only after exact
identity and compatible source-backed date blocking.

## Consequences

False negatives are accepted in preference to harmful false merges. Parent and
subsidiary, brand and legal entity, and near matches remain separate without
review.
