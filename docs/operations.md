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
.venv/bin/breachgazette validate-aliases --json
```

The proposal report is private operational state. Never bulk-approve it.
Verify legal identity or explicit cross-reference evidence at official
sources, then record either an approved or rejected decision. A catalogue
change is code-reviewed and tested before it can affect a publication.

## Relationship review

Generate a stable decision ID from the candidate and its exact sorted record
IDs, then validate the separate catalogue:

```bash
.venv/bin/breachgazette relationship-decision-id \
  rel_000000000000000000000000 \
  --record-id source:one --record-id source:two --json
.venv/bin/breachgazette validate-relationships --json
```

`confirmed_related`, `rejected`, and `unresolved` are explicit review outcomes.
A rejection suppresses the candidate. A confirmation changes only the
displayed relationship status and never merges source records.

## Retention, backup, and restore

The committed policy bounds managed private-state directories to 1 GiB,
retains the latest 53 weekly health-history reports, and allows archives up to
1.25 GiB. Immutable events, source state, manifests, checkpoints, and the
latest health report are never compaction candidates.

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
  /secure/path/breachgazette-state.zip /absolute/empty/restore-root --json
```

Compaction is a dry run unless `--apply` is supplied. Restore accepts only
managed regular files, rejects traversal and symbolic links, enforces byte
bounds, and requires an absent or empty destination.

## Opt-in scheduled update

`.github/workflows/scheduled-private-update.yml` runs at `23 17 * * 1` UTC,
but the scheduled job is inert until all of these are deliberately configured:

- `BREACHGAZETTE_SCHEDULE_ENABLED=true` repository variable;
- `BREACHGAZETTE_DATA_REPOSITORY` pointing to the separate private state
  repository;
- `BREACHGAZETTE_DATA_DEPLOY_KEY` containing a write-scoped deploy key for only
  that private repository.

Manual dispatch defaults `persist_private_state` to false. The workflow runs
`update-cycle --promote` against the private checkout; that command verifies an
isolated candidate before replacing the checkout contents. It commits and
pushes private state only on an enabled schedule or an explicitly persistent
manual run. A failed candidate never replaces the checkout.

The health artifact is retained for 14 days and contains counts, checksums,
timestamps, states, and bounded reasons, not source records. The job summary
contains only source ID, status, count, and overall result. GitHub’s normal
failed-run notification is the default operator alert. GitHub Pages publication
remains a separate manual workflow.

## Publication

```bash
publication_dir="$(mktemp -d /tmp/breachgazette-publication.XXXXXX)"
.venv/bin/breachgazette build-site-data \
  --data-root "$BREACHGAZETTE_DATA_ROOT" --output "$publication_dir"
cd site
BREACHGAZETTE_SITE_DATA_DIR="$publication_dir" npm run build
../.venv/bin/breachgazette audit-public-tree dist
```

Never place the real data root inside the repository, upload raw records as a
workflow artifact, or publish a test fixture. Schedules require a separate
review of source load, rights, private-repository retention, failure reporting,
and operator ownership before enablement.
