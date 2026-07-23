# Relationship methodology

Relationship generation considers named notification records only. Aggregate
metrics and regulatory actions do not enter incident grouping.

The initial blocking rule requires:

1. different source IDs;
2. an exact conservative organization-name key; and
3. at least one identical compatible, source-backed occurrence, awareness,
   submission, or public-notification date.

The candidate ID is deterministic over sorted record IDs and displayed
reasons. Every result is labelled `possibly_related_event` and says that it is
not proof of the same underlying event. Same-organization records with
different dates, fuzzy names, parent-subsidiary pairs, and weak population or
cause similarity remain ungrouped.
