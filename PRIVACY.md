# Privacy policy

Breach Gazette is a privacy-minimised publication of organization-level
information from official public sources.

## Retained source fields

The data model retains source and record identifiers, official organization or
agency name, the source-defined entity role, jurisdiction, regulator,
reporting scheme, publication level, coverage type, source dates with explicit
meanings, affected-population measures where published, bounded cause and
information-category labels, source revision, observation times, source link,
and limitations.

Organization names are public source labels. Exact normalization and reviewed
aliases may connect those labels, but similarity creates private review
proposals only and does not merge identities.

## Excluded fields

Breach Gazette excludes victim names, personal email addresses, telephone
numbers, street addresses, personal identifiers, credentials, contact fields,
complete narratives, complete breach letters, sample notification letters,
complete regulator decisions, attachments, portal form state, and source
cookies. A complete public source page is not republished.

There are no accounts, visitor profiles, analytics, cookies, remote fonts,
search telemetry, or notification promises. Search, Bloom routing, filters,
and formula-safe CSV export run locally in the browser against same-origin
bounded static partitions. No browser-local watchlist is included in this
release.

## Private and public data

Raw retrievals and durable production state live at the operator-configured
`BREACHGAZETTE_DATA_ROOT`, outside the repository. The public build receives only
a temporary, validated, derived publication directory. The repository contains
synthetic fixtures labelled `test_fixture`; production commands reject them.

To delete local operational data, stop update and build processes, verify the
exact configured private root, and remove that root through the operator's
normal recoverable deletion procedure. Deleting private state also deletes
local observation history. Public correction requests should identify the
official source and field without supplying personal data.
