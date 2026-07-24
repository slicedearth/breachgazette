# Operations

## Manual update

Configure an absolute private root, validate policies, and run the fixed-source
update:

```bash
export BREACHGAZETTE_DATA_ROOT=/absolute/private/path/breachgazette-data
.venv/bin/breachgazette validate-source-policies
.venv/bin/breachgazette validate-monitoring
.venv/bin/breachgazette update-cycle \
  --data-root "$BREACHGAZETTE_DATA_ROOT" \
  --promote \
  --json
```

Review per-source counts, rejections, revision, checksum, completeness, latest
attempt, and last complete update. A source failure preserves prior state and
writes a failed checkpoint with a non-sensitive message.

`validate-source-policies` also rejects a rights review dated in the future or
more than 366 days ago. Re-check official terms and attribution before updating
that date; advancing it is not a clerical version bump.

The candidate is copied beside the configured root without `.git`, updated,
health-checked, published into a temporary directory, privacy-audited,
compacted, and size-checked. Promotion moves the original root aside, preserves
its repository metadata, installs the verified candidate, and rolls back if
that swap fails. Without `--promote`, the complete cycle is a non-mutating
rehearsal.

The monitoring catalogue also enforces a reviewed minimum record count,
minimum retained fraction, maximum growth factor, and 240-hour freshness
boundary for the weekly schedule. A large legitimate source change therefore
requires review rather than silently replacing complete state.

## Alias review

```bash
.venv/bin/breachgazette propose-aliases \
  --data-root "$BREACHGAZETTE_DATA_ROOT" \
  --output "$BREACHGAZETTE_DATA_ROOT/reports/alias-proposals.json" \
  --json
.venv/bin/breachgazette alias-decision-id \
  "Source-reported alias" "Reviewed canonical name" --json
.venv/bin/breachgazette validate-aliases \
  --data-root "$BREACHGAZETTE_DATA_ROOT" --json
```

The proposal report is private operational state. Never bulk-approve it.
Verify legal identity or explicit cross-reference evidence at official
sources, then record either an approved or rejected decision in
`$BREACHGAZETTE_DATA_ROOT/reviews/organization-aliases.yml`. The private
catalogue must be reviewed and validated before it can affect a publication.

## Relationship review

Generate a stable decision ID from the candidate and its exact sorted record
IDs, then validate the separate catalogue:

```bash
.venv/bin/breachgazette relationship-decision-id \
  rel_000000000000000000000000 \
  --record-id source:one --record-id source:two --json
.venv/bin/breachgazette validate-relationships \
  --data-root "$BREACHGAZETTE_DATA_ROOT" --json
```

`confirmed_related`, `rejected`, and `unresolved` are explicit review outcomes.
A rejection suppresses the candidate. A confirmation changes only the
displayed relationship status and never merges source records. Decisions live
at `$BREACHGAZETTE_DATA_ROOT/reviews/relationship-decisions.yml`; they are
private operational state and must not be committed to the public repository.

## Retention, backup, and restore

The committed policy bounds managed private-state directories to 1 GiB,
retains the latest 53 weekly health-history reports, and allows archives up to
1.25 GiB. Immutable events, source state, manifests, checkpoints, and the
latest health report are never compaction candidates. Review catalogues are
included in managed backup, restore, and size accounting.

```bash
.venv/bin/breachgazette state-inventory \
  --data-root "$BREACHGAZETTE_DATA_ROOT" --json
.venv/bin/breachgazette compact-state \
  --data-root "$BREACHGAZETTE_DATA_ROOT" --json
.venv/bin/breachgazette compact-state \
  --data-root "$BREACHGAZETTE_DATA_ROOT" --apply --json
.venv/bin/breachgazette backup-state /secure/path/breachgazette-state.zip \
  --data-root "$BREACHGAZETTE_DATA_ROOT" --json
.venv/bin/breachgazette restore-state \
  /secure/path/breachgazette-state.zip /absolute/empty/restore-root \
  --expected-sha256 "<checksum_sha256 from backup-state output>" --json
```

Compaction is a dry run unless `--apply` is supplied. Restore accepts only
managed regular files, rejects traversal and symbolic links, enforces byte
bounds, and requires an absent or empty destination. It verifies the complete
archive against the exact SHA-256 emitted by `backup-state` before creating the
restore destination. Inventory hashing and ZIP creation stream bounded chunks,
so the archive path does not require loading the entire private state into
memory. Record the expected checksum separately from the archive, such as in an
encrypted backup catalogue. A checksum detects alteration only while that
expected value remains trusted; it is not a digital signature.

### Durable-store boundary

For the current bounded state, use a dedicated private Git repository as the
authoritative operational store. It contains only managed private-state
directories and its own repository metadata; it must never be nested in,
submoduled into, or copied to the public source repository. Netlify is not a
state store and receives only the audited `site/dist` output.

Use the private `Breach Gazette State` GitHub App for cross-repository access.
The App must be installed only on the private state repository, with Contents
read and write as its sole configurable repository permission and webhooks
disabled. Store its Client ID as the
`BREACHGAZETTE_STATE_APP_CLIENT_ID` repository variable and its private key as
the `BREACHGAZETTE_STATE_APP_PRIVATE_KEY` repository secret in the public source
repository.

Each job mints a repository-specific installation token immediately before
checking out private state. Publication explicitly requests Contents read
access; the enabled updater explicitly requests Contents write access. Tokens
expire after one hour and are revoked when their jobs finish. The App private
key is the remaining long-lived credential: keep it only in Actions secrets,
rotate it after suspected exposure, and protect `main` from unreviewed workflow
changes.

A private Git repository is not an independent backup and Git history does not
enforce deletion or retention. Keep a separately verified backup on encrypted
local or off-site storage. `backup-state` produces a bounded ZIP archive but
does not encrypt it; protect the destination filesystem or encrypt the archive
before it leaves the trusted operator environment. If source terms or a valid
privacy request require historical removal, review and purge private Git
history as well as the current tree.

## Opt-in scheduled update

`.github/workflows/scheduled-private-update.yml` runs at `23 17 * * 1` UTC,
but the scheduled job is inert until all of these are deliberately configured:

- `BREACHGAZETTE_SCHEDULE_ENABLED=true` repository variable;
- `BREACHGAZETTE_DATA_REPOSITORY` pointing to the separate private state
  repository;
- `BREACHGAZETTE_DATA_REF` naming the writable private-state branch used for
  automatic updates and publication;
- `BREACHGAZETTE_STATE_APP_CLIENT_ID` and
  `BREACHGAZETTE_STATE_APP_PRIVATE_KEY` for the repository-scoped App;
- the Netlify settings listed below.

Manual dispatch defaults `persist_private_state` to false. The workflow runs
`update-cycle --promote` against the private checkout; that command verifies an
isolated candidate before replacing the checkout contents. It commits and
pushes private state only on an enabled schedule or an explicitly persistent
manual run. A successful persisted update then calls the read-only publication
workflow for the configured private branch. A rehearsal does not publish, and a
failed candidate never replaces the checkout or reaches Netlify.

The health artifact is retained for 14 days and contains counts, checksums,
timestamps, states, and bounded reasons, not source records. The job summary
contains only source ID, status, count, and overall result. GitHub’s normal
failed-run notification is the default operator alert.

## Publication

```bash
publication_dir="$(mktemp -d /tmp/breachgazette-publication.XXXXXX)"
.venv/bin/breachgazette build-site-data \
  --data-root "$BREACHGAZETTE_DATA_ROOT" --output "$publication_dir"
cd site
BREACHGAZETTE_SITE_DATA_DIR="$publication_dir" \
  BREACHGAZETTE_SITE_URL="https://breachgazette.example" \
  npm run build:budget
../.venv/bin/breachgazette audit-public-tree dist
```

Never place the real data root inside the repository, upload raw records as a
workflow artifact, or publish a test fixture. Schedules require a separate
review of source load, rights, private-repository retention, failure reporting,
and operator ownership before enablement.

The Netlify publication workflow requires:

- `BREACHGAZETTE_DATA_REPOSITORY`, the separate private state repository;
- `BREACHGAZETTE_DATA_REF`, its configured writable production branch;
- `BREACHGAZETTE_SITE_URL`, the final HTTPS origin;
- `NETLIFY_SITE_ID`, the target site identifier;
- `NETLIFY_AUTH_TOKEN`, a dedicated token stored only as a repository secret;
- `BREACHGAZETTE_STATE_APP_CLIENT_ID`, the private state App's Client ID;
- `BREACHGAZETTE_STATE_APP_PRIVATE_KEY`, the private state App's private key.

Publication runs automatically after successful `main` CI and after a
successful scheduled or explicitly persisted private-state update. A manual
dispatch remains available for an exact private-state commit or tag. The
workflow records the resolved source and private-state commit IDs, audits the
result, and atomically deploys only `site/dist`. Do not enable Netlify's
connected repository build because it has no reason to receive the private
state repository or its credentials.

Before enabling unattended publication:

- protect the public repository's `main` branch and require CI and CodeQL for
  pull requests;
- restrict the GitHub `netlify-production` environment to the `main` branch,
  without a required reviewer if publication must remain unattended;
- use a dedicated, revocable Netlify token rather than a personal general-use
  credential;
- keep Netlify connected builds disabled so GitHub Actions is the only
  production publisher;
- manually publish one exact private-state commit, verify the live response
  headers and site content, then enable the schedule.

These are provider settings and are not established by the repository. Review
them after changes to repository ownership, branch protection, environments,
tokens, or the Netlify site.
