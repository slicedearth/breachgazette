# Relationship methodology

Relationship generation considers named notification records only. Aggregate
metrics and regulatory actions do not enter incident grouping.

The initial blocking rule requires:

1. different source IDs;
2. an exact conservative organization-name key; and
3. at least one identical compatible, source-backed occurrence, awareness,
   submission, or public-notification date.

The candidate ID is deterministic over sorted record IDs and displayed
reasons. New results are labelled `possibly_related_event` and say that they
are not proof of the same underlying event. Same-organization records with
different dates, fuzzy names, parent-subsidiary pairs, and weak population or
cause similarity remain ungrouped.

Reviewed decisions live in the private
`$BREACHGAZETTE_DATA_ROOT/reviews/relationship-decisions.yml` catalogue,
separate from organization aliases. Each decision records a stable ID, exact
sorted record IDs, evidence, date, note, and version. `confirmed_related`
changes the public relationship label to likely same publicly reported event,
`unresolved` preserves uncertainty, and `rejected` suppresses the candidate.
No outcome merges provenance, source roles, dates, thresholds, entities, or
legal meaning.
