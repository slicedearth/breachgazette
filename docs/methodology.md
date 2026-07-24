# Methodology

## Source and date semantics

Every record retains source, regulator, jurisdiction, scheme, threshold,
publication level, coverage type, named-entity role, revision, retrieval and
observation times, source URL, and limitations. Occurrence, discovery,
awareness, consumer notification, regulator submission, public notification,
source publication, and reporting-period dates remain distinct.

A source-observed date remains visible as raw provenance when it conflicts with
the source record's own chronology. It receives a `source_conflict` state and
no normalized date, so it cannot influence year facets, ordering, feeds, or
candidate relationships until the official source corrects it.

## Notification, incident, anonymous row, and aggregate

A notification is a source record, not automatically one unique incident.
Multiple source records can describe one event, while one organization can
have multiple unrelated events. Aggregate cells are metrics without named
organizations and never enter incident grouping.

An anonymized notification source can publish report-level characteristics
without organization names. Those rows never enter organization resolution.
For CNIL, the complete published CSV is validated transiently and only grouped
counts are retained. Category-membership counts remain distinct from
notification-row counts because one row can carry more than one category.

## Organization roles and identity

The notifier, affected entity, public agency, service provider, covered entity,
business associate, alleged respondent, and determined respondent are not
interchangeable. Organization resolution uses exact deterministic normalized
names or reviewed aliases only.

## Candidate grouping

Candidate relationships require exact organization identity and an identical
source-backed compatible date across different sources. Every candidate shows
its reasons and a disclaimer. Weak similarity is blocked and no candidate
merges provenance.

## Time, windows, and corrections

Complete comparable snapshots produce deterministic first-observed,
corrected, and source-status change events. Rolling-window disappearance is not
treated as deletion, resolution, or remediation. Partial snapshots cannot
create disappearance events. Corrections are verified against the official
source; curated policy and alias changes require review.

## Cross-country comparison

Comparisons are published only when period, threshold, population scope, unit,
coverage, and source role are displayed and compatible. Breach Gazette does not
compute a generic Australia-versus-US score or imply that higher notification
counts mean weaker security.
