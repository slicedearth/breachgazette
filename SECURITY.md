# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub's private vulnerability
reporting feature for this repository. Do not include victim data, credentials,
breach letters, or other sensitive source material in a public issue.

## Security model

Breach Gazette has no public submission endpoint, account system, victim search,
notification service, runtime database, or production application server. The
deployed product is a static Astro site.

Official-source clients are fixed in code. They allow only reviewed
credential-free HTTPS origins and paths, validate redirects, impose timeouts,
deadlines, page and byte limits, require expected content types, and stop on
schema drift. The CLI accepts source identifiers, not arbitrary URLs or
Socrata datasets.

All source input is hostile. Normalized data and public output are checked for
personal contact data, credentials, unsafe URLs, markup, scripts, control and
bidirectional characters, spreadsheet formula prefixes, and unexpectedly long
text. Breach Gazette does not retrieve breach-notification letters or complete
regulator decisions.

Production state, raw retrieval caches, manifests, checkpoints, and immutable
events remain in a private data root outside Git and the static site.
Production publication refuses fixture state.

## Workflows and dependencies

Workflows use least privilege, immutable action SHAs, explicit timeouts, locked
dependencies, and no live sources in CI. Pages deployment is manual-only and
requires configured real source-derived data. Dry-run update workflows make no
commit, push, issue, or deployment. The separate scheduled workflow is disabled
unless explicitly enabled and can push only its verified candidate to the
configured private state repository through that repository's scoped deploy
key. It cannot write the public source repository.

Python and npm dependencies are fully pinned in committed lockfiles. CI runs
`pip-audit` and `npm audit --audit-level=high`. See
[the dependency policy](docs/dependency-policy.md).
