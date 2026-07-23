# United States sources

## Washington

The adapter uses fixed Socrata dataset IDs `sb4j-ca4h` and `padd-mby7`, exact
field lists, count reconciliation, bounded ordered pagination, and a
one-to-many information-category join. The public threshold is more than 500
Washington residents. The named entity is the notifier and may differ from the
entity where an event occurred. A dataset-specific licence identifier was not
present at review, so redistribution remains approved with conditions and
ongoing terms review.

## California

The official CSV contains organization name, occurrence dates where known, and
reported date. It provides no stable row ID, so Breach Gazette creates a
deterministic hash plus duplicate ordinal. The source threshold is more than
500 California residents. The notifier may differ from the affected entity.
The current official CSV has one historical row with an omitted organization
name. That row remains a notification with an explicit `source_omitted` state
and is excluded from entity resolution. Sample letters are not retrieved or
published.

## HHS OCR

The official portal separates a current 24-month list from an archive for
breaches affecting 500 or more individuals. No stable bounded
machine-readable public export contract was verified. The source is deferred
rather than automated through brittle stateful JSF browser behavior. The
current ingestion contract requires partial-result detection and preservation
of covered-entity, business-associate, addendum, and rolling-window semantics.
