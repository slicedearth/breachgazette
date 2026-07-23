# Operations

## Manual update

Configure an absolute private root, validate policies, and run the fixed-source
update:

```bash
export BREACHGAZETTE_DATA_ROOT=/absolute/private/path/breachgazette-data
.venv/bin/breachgazette validate-source-policies
.venv/bin/breachgazette update --data-root "$BREACHGAZETTE_DATA_ROOT" --json
```

Review per-source counts, rejections, revision, checksum, completeness, latest
attempt, and last complete update. A source failure preserves prior state and
writes a failed checkpoint with a non-sensitive message.

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
review of source load, rights, retention, failure reporting, and operator
ownership.
