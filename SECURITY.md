# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub's private vulnerability
reporting feature for this repository. Do not include victim data, credentials,
breach letters, or other sensitive source material in a public issue.
The deployed site publishes the same private-reporting route at
`/.well-known/security.txt`.

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
events remain in a separate private data root outside the public source
repository and static site. Reviewed alias and relationship catalogues also
remain private. The public repository contains only deterministic synthetic
fixtures and empty review-catalogue schemas. Production publication refuses
fixture state.

## Workflows and dependencies

Workflows use least privilege, immutable action SHAs, explicit timeouts, locked
dependencies, and no live sources in CI. Netlify publication runs only after
successful `main` CI, after a verified persisted private-state update, or by
manual dispatch. A private GitHub App installed only on the state repository
mints repository-specific installation tokens that expire after one hour. The
publication job requests read-only Contents access and uploads only the audited
static tree. Dry-run update workflows make no commit, push, issue, or
deployment. The separate scheduled workflow is disabled unless explicitly
enabled and requests write-scoped Contents access only while promoting and
pushing its verified candidate. Its follow-on publication job mints a new
read-only token. Neither job can write the public source repository.

Python and npm dependencies are fully pinned in committed lockfiles. CI runs
security-focused Ruff checks, `pip-audit`, `npm audit --audit-level=high`, and
CodeQL for Python and JavaScript/TypeScript. The public-tree gate rejects
hidden files, sensitive filenames, unknown file types, symbolic links, remote
analytics markers, fixture data, and output that exceeds its file, byte, or
page budgets. The publication workflow validates Netlify's returned HTTPS URL
and verifies the live CSP, HSTS, framing, referrer, permissions, content-type,
and opener policies after each deploy. See
[the dependency policy](docs/dependency-policy.md).

Netlify applies committed response headers for transport security, framing
protection, content-type sniffing protection, referrer policy, permissions, and
a restrictive content security policy. HTML metadata remains defense in depth;
it cannot enforce `Strict-Transport-Security` or CSP `frame-ancestors`.
