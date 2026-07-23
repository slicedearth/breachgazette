# Entity resolution

The resolver case-folds Unicode, normalizes spacing and punctuation, removes a
small reviewed set of common legal suffixes, and compares the resulting exact
key. Diacritics are normalized deterministically. It does not use edit
distance, embeddings, web search, domain inference, or organization metadata.

A curated alias maps one exact normalized source name to a reviewed canonical
key and records a deterministic decision ID, status, source set, review date,
evidence, note, and resolver version. Approved alias chains and cycles are
rejected. Parent and subsidiary, brand and legal entity, renamed companies,
and near matches remain separate without an explicit reviewed alias.

Every alias retains the source name and role. One resolved organization can
therefore appear as a notifier in one source and an alleged respondent in
another without collapsing those meanings.

`breachgazette propose-aliases` produces a bounded private report from
token-spacing and contained-token blocks. Proposals never enter the resolver.
An operator verifies official evidence, records an approved or rejected
decision in
`$BREACHGAZETTE_DATA_ROOT/reviews/organization-aliases.yml`, generates its
stable ID with `breachgazette alias-decision-id`, and runs
`breachgazette validate-aliases --data-root "$BREACHGAZETTE_DATA_ROOT"`.
Rejected decisions remain in the private catalogue to suppress repeat
proposals.
