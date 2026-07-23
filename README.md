# Breach Gazette

**Public breach notifications, connected and explained.**

Breach Gazette is a provenance-first public data platform for official Australian
and United States breach-notification statistics, public notification
registers, and regulatory actions. It preserves the source-specific difference
between aggregate statistics, named notifications, investigations,
determinations, court proceedings, and judgments.

Breach Gazette does not independently verify the underlying events. It does not
score organizations, identify victims, retrieve notification letters, or turn
an allegation into a finding.

## Initial source coverage

| Source | Publication model | First-release boundary |
| --- | --- | --- |
| OAIC NDB statistics | National aggregate | Current official Data.gov.au XLSX |
| NSW IPC MNDB snapshot | State aggregate | Reviewed sector table in the latest indexed PDF |
| NSW IPC Public Notifications Register | Rolling named register | Register rows and safe source links only |
| OAIC regulatory actions | Selective legal-status timeline | Reviewed fixed official OAIC URLs |
| Washington Attorney General | Named notifications | Fixed Socrata datasets and exact fields |
| California Attorney General | Named notifications | Official full CSV, without notice letters |
| Massachusetts OCABR | Named notifications | Reviewed 2025 and 2026 annual reports, without notice letters |
| HHS OCR | Deferred | No stable bounded machine-readable public-list contract verified |

Aggregate rows never become named incident records. A named notifier is not
silently relabelled as the entity where an event occurred. Cross-jurisdiction
relationships remain explainable candidates until reviewed.

## Architecture

The Python 3.12 pipeline uses source-specific HTTPS clients, Pydantic v2
contracts, deterministic normalization, immutable comparison events, reviewed
organization-alias and relationship decisions, source-freshness monitoring,
record-count drift guards, transactional update cycles, bounded retention and
restore tools, and fail-closed privacy checks. Durable source state lives
outside this repository under `BREACHGAZETTE_DATA_ROOT`.

Astro renders a static website from a temporary privacy-minimised publication
directory. Production builds refuse test fixtures and missing required real
sources. Browser search uses a compact facet and trigram-Bloom manifest, loads
only candidate source/year partitions, and can export every filtered match to
a formula-safe CSV. Filter state can be copied as a URL fragment without
sending the search to a server. A privacy-minimised Atom feed exposes the
latest public notifications. There is no runtime application server, account
system, analytics, cookie, or remotely collected search query.

See [the architecture](docs/architecture.md), [methodology](docs/methodology.md),
and [data dictionary](docs/data-dictionary.md) for the complete model.

## Local setup

Requirements:

- Python 3.12 or later
- Node.js 24
- npm 11

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip==26.1.2
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install -e . --no-deps --no-build-isolation
cd site
npm ci
```

Run deterministic tests:

```bash
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest --cov=breachgazette --cov-report=term-missing --cov-fail-under=80
.venv/bin/breachgazette validate-monitoring --json
.venv/bin/breachgazette validate-aliases \
  --catalogue tests/fixtures/reviews/organization-aliases.yml --json
.venv/bin/breachgazette validate-relationships \
  --catalogue tests/fixtures/reviews/relationship-decisions.yml --json
cd site
npm run check:test
npm run build:test
npm run test:e2e
```

The local browser command uses Chromium only. Linux CI runs Chromium, Firefox,
and WebKit through `npm run test:e2e:ci`; this avoids launching Playwright
browser bundles that are incompatible with older macOS releases.

Ordinary tests use only test-specific fixtures and injected transports. A
fixture can be ingested only into a data-root directory whose final name
contains `fixture`:

```bash
.venv/bin/breachgazette ingest-fixture \
  tests/fixtures/australia/oaic-aggregate.json \
  --data-root /tmp/breachgazette-fixture
```

## Manual real-source update

The live update is deliberate, bounded, and separate from ordinary tests:

```bash
export BREACHGAZETTE_DATA_ROOT=/absolute/private/path/breachgazette-data
.venv/bin/breachgazette validate-source-policies
.venv/bin/breachgazette validate-monitoring
.venv/bin/breachgazette update-cycle \
  --data-root "$BREACHGAZETTE_DATA_ROOT" \
  --promote
```

The cycle updates an isolated copy, runs health, quality, publication, privacy,
and public-tree gates, then promotes only the complete candidate. Without
`--promote`, it is a non-mutating full-cycle rehearsal. Each source also keeps
its previous complete snapshot when an individual retrieval fails. Source
policy validation rejects future-dated or more-than-366-day-old rights reviews.

## Reviewed organization aliases

Near-name matching creates private review proposals only. It never changes a
public organization identity:

```bash
.venv/bin/breachgazette propose-aliases \
  --data-root "$BREACHGAZETTE_DATA_ROOT" \
  --output "$BREACHGAZETTE_DATA_ROOT/reports/alias-proposals.json"
.venv/bin/breachgazette alias-decision-id \
  "Source-reported alias" "Reviewed canonical name" --json
.venv/bin/breachgazette validate-aliases \
  --data-root "$BREACHGAZETTE_DATA_ROOT" --json
```

An operator must verify official evidence and add an approved or rejected
decision to
`$BREACHGAZETTE_DATA_ROOT/reviews/organization-aliases.yml`. Reviewed
catalogues are private operational state and are never committed. Decisions
are deterministic, evidence-bearing, non-chained, and auditable. Rejected
pairs are retained so they are not repeatedly proposed.

Reviewed incident-link decisions use a separate catalogue:

```bash
.venv/bin/breachgazette relationship-decision-id \
  rel_000000000000000000000000 \
  --record-id source:one --record-id source:two --json
.venv/bin/breachgazette validate-relationships \
  --data-root "$BREACHGAZETTE_DATA_ROOT" --json
```

Confirmed links remain evidence-backed public-record relationships, not merged
incidents or legal findings.

## Scheduled private updates

The scheduled workflow is implemented but disabled by default. It runs only
after the repository variable `BREACHGAZETTE_SCHEDULE_ENABLED` is explicitly set
to `true`. Manual runs default to dry-run behavior unless
`persist_private_state` is selected.

Every run invokes the same tested candidate transaction used locally, writes a
sanitized source-ID/status/count job summary, uploads only the non-sensitive
health report, and pushes private state only if all source, freshness, quality,
privacy, and publication gates pass. See [operations](docs/operations.md).

## Production static build

Generate temporary real publication data, then point Astro at it:

```bash
publication_dir="$(mktemp -d /tmp/breachgazette-publication.XXXXXX)"
.venv/bin/breachgazette build-site-data \
  --data-root "$BREACHGAZETTE_DATA_ROOT" \
  --output "$publication_dir"
cd site
BREACHGAZETTE_SITE_DATA_DIR="$publication_dir" npm run build:budget
../.venv/bin/breachgazette audit-public-tree dist
```

The production build fails if the real data root is incomplete or if the
publication data declares itself to be a fixture. The build and public-tree
audits also enforce time, file-count, HTML-size, and total-size budgets.
Generated production records, search indexes, and publication data are not
committed.

## Privacy and safety

The pipeline excludes victim and contact information, complete narratives,
sample notice letters, complete regulator decisions, credentials, and form
state. It scans normalized state, generated publication data, and the final
static tree for personal contact patterns, unsafe markup, dangerous URLs,
spreadsheet formulas, control characters, and unapproved fields.

Search and filtering run in the browser against the published bounded dataset.
Shareable filters use a URL fragment, which browsers do not send in HTTP
requests. No query leaves the visitor's device. Reviewed alias and relationship
catalogues remain private operational state. See [PRIVACY.md](PRIVACY.md) and
[SECURITY.md](SECURITY.md).

## Source freshness and corrections

Source coverage pages show the latest attempt, last successful update,
revision or checksum, accepted and rejected counts, and source-specific
limitations. Corrections should be checked against the official source before
the curated policy or manifest is changed. Use the correction process
documented in [docs/methodology.md](docs/methodology.md).

## Limitations

- Official sources have different thresholds, populations, dates, windows, and
  legal meanings.
- Notification counts do not necessarily equal unique real-world incidents.
- Public registers may be selective or rolling.
- Organization names are source-reported and can be corrected.
- Relationship candidates are not proof of a shared event.
- No generic Australia-versus-US comparison is calculated.
- Search routing uses a false-positive-only Bloom index; candidate partitions
  can be loaded unnecessarily, but matching partitions must never be omitted.
- Scheduled updates remain inert until the private repository, scoped deploy
  key, and explicit enablement variable are configured.
- Washington's dataset has no dataset-specific licence identifier; its
  publication boundary requires ongoing review.
- HHS remains deferred rather than using brittle browser automation.

## Licence boundary

Original source code and project-authored documentation are licensed under the
[MIT Licence](LICENSE). That licence does not relicense official source data.
OAIC, NSW IPC, Washington, California, Massachusetts, and other source-derived
material keeps its own attribution, terms, and limitations. See
[docs/legal-and-licensing.md](docs/legal-and-licensing.md) and [NOTICE](NOTICE).
