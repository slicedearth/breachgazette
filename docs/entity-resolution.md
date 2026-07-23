# Entity resolution

The resolver case-folds Unicode, normalizes spacing and punctuation, removes a
small reviewed set of common legal suffixes, and compares the resulting exact
key. Diacritics are normalized deterministically. It does not use edit
distance, embeddings, web search, domain inference, or organization metadata.

A curated alias maps one exact normalized source name to a reviewed canonical
key and records its evidence and resolver version. Parent and subsidiary,
brand and legal entity, renamed companies, and near matches remain separate
without an explicit reviewed alias.

Every alias retains the source name and role. One resolved organization can
therefore appear as a notifier in one source and an alleged respondent in
another without collapsing those meanings.
