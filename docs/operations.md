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
that swap fails. Without `--promote`, the complete cycle leaves the authoritative
data root unchanged. A coordination lock file remains beside that root; it is
not source state or a health report.

Individual `update-source` commands also stage a complete generation under a
single-writer filesystem lock. A failed write or promotion leaves prior records,
snapshots and events intact; the failed checkpoint is a separate diagnostic.
The lock is local to one filesystem and is not a distributed scheduler lock.
Source IDs must be unique within each source snapshot before persistence.

Use `--attempt-report /absolute/diagnostic/path/attempt.json` to retain a bounded
sanitised cycle report outside authoritative state. This is an explicit write,
including during a rehearsal. Without that option, a rehearsal does not write a
report into production state. Attempts distinguish failed, complete and
not-attempted sources, and report publication failures separately from retrieval.
Candidate accepted counts and the previous production count/update time are
separate fields; a discarded attempt never advances the production timestamp.
The scheduled workflow retains that report even when a candidate is discarded.
The public site still describes the last successfully published generation; it
cannot expose a failed deployment that never reached the static host. Bounded
public recovery history includes only retained health observations, not every
failed or discarded attempt.

OAIC semantic metric IDs use normalization version 2.0. Existing 1.0 state is
blocked from update and unattended publication until its mapping is reviewed.
Prepare a private draft outside both the authoritative state root and source
checkout:

```bash
.venv/bin/breachgazette plan-oaic-migration \
  --data-root "$BREACHGAZETTE_DATA_ROOT" \
  --output /secure/path/oaic-identity-plan.json --json
.venv/bin/breachgazette migrate-oaic-identities \
  --data-root "$BREACHGAZETTE_DATA_ROOT" \
  --plan /secure/path/oaic-identity-plan.json --json
```

Both commands leave source state unchanged. The draft rejects ambiguous
semantic metrics, records an exact fingerprint of all managed state, and starts
with `approved: false`. Review the mapping against official reporting periods
and scopes on a disposable copy. Do not replace IDs solely to bypass an update
failure. Keep the mapping private and mark `approved: true` only after review.

When legacy sector context is missing or an exact source-of-breach cell is
repeated, provide the checksum-matched original workbook with `--workbook`
to both commands and to the application command below. This creates a version
1.1 evidence plan. The workbook remains private, outside both state and source
roots; it is re-read and verified during every dry run and application. Row
coordinates are used only to verify old IDs against that exact evidence, never
as new metric identities. All legacy rows must be covered. Only missing sector
parents can be restored; other field changes, incomplete evidence, conflicting
repetitions or repetitions with different observation provenance are rejected.

Create an independent backup of that same generation using `backup-state`.
Retain its checksum separately. Only an explicitly authorised operator should
apply the reviewed transition:

```bash
.venv/bin/breachgazette migrate-oaic-identities \
  --data-root "$BREACHGAZETTE_DATA_ROOT" \
  --plan /secure/path/oaic-identity-plan.json \
  --backup /secure/path/breachgazette-state.zip \
  --expected-backup-sha256 "<checksum_sha256 from backup-state>" \
  --apply --json
```

Application acquires the single-writer lock, checks that the reviewed generation
has not changed, restores and verifies the complete backup in a temporary
directory, and stages the transition before promotion. It preserves observation
times, dataset class, repository metadata and historical event bytes.
Identity-only transitions also preserve source snapshots byte for byte.
Plain identity-only plans reject missing or unreconciled sector context in the
Top 5 metrics, including previously prepared plans. Those records require the
checksum-matched workbook route; persisted row order is never used to guess a
sector. Nonempty conflicting context remains rejected rather than silently repaired.
The private `reviews/oaic-identity-bridge.json` retains the approved
old-to-new mapping and backup checksum. A changed generation, unapproved or
modified mapping, stale backup, repeated application or staging failure is
rejected. No migration is performed by an update or publication command.

For a reviewed exact repetition, every old ID remains in the private bridge,
while one representative retains the original metric fields and observation
times. The current snapshot's accepted count is corrected to the unique metric
count without changing retrieval, completion, freshness, revision or source
checksum. Its complete original snapshot is retained in the bridge and verified
backup. Historical events are never removed or rewritten. Ordinary collection
also reconciles only fully identical repeated cells in the source-of-breach
sheet, records the repetition in snapshot notes and discovery counts, and stops
on any conflicting duplicate. This is not incident deduplication.

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

### Interrupted generation promotion

Ordinary exceptions roll promotion back under the single-writer lock. Abrupt
process termination or machine loss can interrupt the directory renames instead.
This can leave the configured root absent with recoverable data in its sibling
`.<root-name>-previous` and `.<root-name>-candidate-*` directories. Do not run a
new update, migration or restore over these paths, and do not delete them.

Pause writers and acquire `state_lock` for the exact configured root before
inspection. Verify the previous generation against an independently recorded
inventory or restored backup. If the root is absent, preserve the candidate for
inspection, return its `.git` directory to the verified previous generation if
that metadata was moved, and rename the verified previous directory back to the
configured root. Check the complete inventory and repository metadata before
releasing the lock. If the root already contains the complete new generation,
retain both generations for review; do not replace it solely because a previous
directory remains. Ambiguous paths or mismatched checksums require operator
review, not automatic recovery. The current protocol has no durable journal and
does not establish crash-atomic promotion or protection against power-loss
filesystem corruption.

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

## Collection timing

The remaining client-lifetime budget is shared across requests, redirects,
network reads and writes, TLS negotiation and retry delays. Request and body
protocol failures use the same bounded retry contract. A connection or TLS
stream returned after the budget expires is closed and rejected.

The blocking backend may spend time in DNS resolution independently of its
socket timeout, or reuse a timeout across multiple address attempts. The budget
checks cannot preempt those operations. They reject a late return rather than
establishing a strict end-to-end wall-clock deadline. A preemptive resolver or
an isolated worker with a bounded termination protocol would need separate
compatibility and recovery review.

## Publication

### Coordinated normalisation cutover

An identity version boundary needs an explicitly authorised cutover, not just
a source-code push. Pause the scheduled-update flag before switching either
production input. Push the source review branch and require its complete hosted
CI, including both analysis languages, before merging the protected production
branch. Old private state will fail closed under the new publication gate.

With the approved source revision active, re-check that the reviewed private
generation still matches its plan and backup. Persist the verified private
transition without force-pushing or overwriting a newer generation. Publish its
exact private commit only after the matching source revision has passed CI.
Verify the deployed publication identity and response headers, then re-enable
the schedule. A failed gate leaves publication and automatic updates paused;
never relax a gate to complete the cutover. All remote steps require operator
approval. A local rehearsal is not an authoritative migration or deployment.

### Offline publication checks

Run the offline preflight before preparing a release:

```bash
.venv/bin/breachgazette deployment-preflight \
  --data-root "$BREACHGAZETTE_DATA_ROOT" --json
```

This reads state without fetching sources or promoting a generation. It checks
source rights and monitoring policy, state bounds, current OAIC identities,
real-data classification, freshness, and a temporary publication's quality,
privacy and public-tree gates. It rejects fixture state and concurrent changes.
Reports contain check names and outcomes, not source records or exception text.
Temporary publication data is removed when the check finishes. The dedicated
temporary private checkout used by the publication workflow is read-only for
this command; migration tooling still refuses state inside the source checkout.

A preflight pass applies only to the inspected private-state generation. It is
not a substitute for hosted CI and both analysis languages at the exact source
revision, a complete static-site build, provider configuration review or live
post-deployment verification. Unattended publication runs this preflight before
building its real output. Legacy identity state fails closed rather than being
silently rewritten during deployment.

```bash
publication_dir="$(mktemp -d /tmp/breachgazette-publication.XXXXXX)"
source_revision="$(git rev-parse HEAD)"
.venv/bin/breachgazette build-site-data \
  --data-root "$BREACHGAZETTE_DATA_ROOT" --output "$publication_dir"
cd site
BREACHGAZETTE_SITE_DATA_DIR="$publication_dir" \
  BREACHGAZETTE_SITE_URL="https://breachgazette.example" \
  BREACHGAZETTE_SOURCE_REVISION="$source_revision" \
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
result, publishes the source revision and publication checksum, and atomically
deploys only `site/dist`. It retains the deployment archive and a provenance
JSON record for 30 days. The JSON binds the archive digest, source revision,
publication checksum, workflow run, and deployment response, but is explicitly
marked unsigned and must not be represented as a cryptographic attestation.
Do not enable Netlify's
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
