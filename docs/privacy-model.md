# Privacy model

Privacy minimization occurs at three publication gates:

1. before a source record enters durable normalized state;
2. before public publication data are generated; and
3. after the static site is built.

The record contracts are allowlists. They omit victim and contact data,
credentials, narrative bodies, breach letters, complete decisions, attachments,
and raw page content. Detector findings contain a redacted fingerprint, field
path, detector ID, and record identity, never the matched sensitive value.

Real state stays outside Git. Public data are temporary, bounded, derived, and
attributed. Synthetic fixtures use fictitious organizations and an explicit
dataset class that production rejects.
