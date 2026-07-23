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
proposals only and does not merge identities. Alias and relationship review
catalogues remain under the private data root; only the minimised effect of an
approved decision can enter generated public output.

## Excluded fields

Breach Gazette excludes victim names, personal email addresses, telephone
numbers, street addresses, personal identifiers, credentials, contact fields,
complete narratives, complete breach letters, sample notification letters,
complete regulator decisions, attachments, portal form state, and source
cookies. A complete public source page is not republished.

There are no accounts, visitor profiles, analytics, cookies, remote fonts,
search telemetry, or notification promises. Search, Bloom routing, filters,
and formula-safe CSV export run locally in the browser against same-origin
bounded static partitions. Copied search links encode bounded filter values in
the URL fragment, which is not included in HTTP requests. The Atom feed
contains only the same privacy-minimised public notification fields. No
browser-local watchlist is included in this release.

Breach Gazette does not add application analytics or request logging. As the
static hosting and CDN provider, Netlify may process ordinary request metadata
such as IP address, requested path, user agent, and timestamp under its own
service terms. Search filters in URL fragments are not sent with those
requests. Optional Netlify analytics or log-export features should remain
disabled unless this policy is reviewed first.

## Private and public data

Raw retrievals and durable production state live at the operator-configured
`BREACHGAZETTE_DATA_ROOT`, outside the public source repository. The public
build receives only a temporary, validated, derived publication directory. The
public repository contains synthetic fixtures labelled `test_fixture` and
empty review-catalogue schemas; production commands reject fixture state.
Generated publication output is not committed, and Netlify receives only the
audited static tree.

To delete local operational data, stop update and build processes, verify the
exact configured private root, and remove that root through the operator's
normal recoverable deletion procedure. If that root is synchronized through a
private Git repository or backup, the same deletion review must cover repository
history and retained backup copies. Deleting private state also deletes local
observation history. Public correction requests should identify the official
source and field without supplying personal data.
