# Relationship methodology

Relationship generation considers named notification records only. Aggregate
metrics and regulatory actions do not enter incident grouping.

The initial blocking rule requires:

1. different source IDs;
2. an exact conservative organization-name key; and
3. at least one identical source-backed occurrence, awareness,
   submission, or public-notification date.

The current rule compares calendar dates across these meanings, not occurrence
intervals or equivalent reporting stages. Equal dates with different meanings
can produce candidates; this is a review signal, not a claim of compatible
chronology. Raw, missing and source-conflict dates do not supply a date key.

The retained `compatible_occurrence_interval` reason code is a legacy identifier,
not a description of interval matching. Its displayed explanation describes
identical dates. Changing that code or reason evidence changes deterministic
candidate IDs and requires reconciliation with existing reviewed decisions.

`date_keys` exposes the current `calendar_date_v1` contract and a tested
`same_meaning_v1` comparison for offline review. Candidate generation uses only
the current contract. The stricter helper is not enabled by a catalogue or CLI
option and does not change published candidate coverage. It compares identical
dates with identical meanings, not overlapping occurrence intervals.

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
