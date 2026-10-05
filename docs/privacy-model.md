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

Alias proposals remain private operational reports and cannot change public
identities. Source-health artifacts contain source IDs, counts, checksums,
timestamps, statuses, and bounded reasons, not source records. Public search
uses static same-origin partitions and sends no query to an application server.
The query-routing Bloom values are derived indexes of public records, not
encryption or a confidentiality boundary. They are exempt
from text-pattern detectors only by exact field name; the underlying public
records still pass the full privacy audit. CSV export is user-initiated,
browser-local, field-allowlisted, and formula-neutralized.

Generated search-partition asset names have a separate narrow exemption only
after their source/year/page identifier and digest-derived suffix agree in a
typed manifest. Arbitrary source fields named `asset` remain subject to text
detectors, and formula detection is not disabled.

The literal fragment query is not sent in HTTP requests. Candidate partition
requests can still reveal which source and year groups were accessed in hosting
logs. The index does not promise to hide that access pattern.
