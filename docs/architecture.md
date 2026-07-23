# Architecture

Breach Gazette is a local-first pipeline and a static publication.

Fixed source adapters retrieve bounded official data through a shared hardened
transport. Pydantic contracts preserve provenance and distinguish aggregate,
notification, and regulatory records. Privacy auditing runs before normalized
state, before publication, and against the built tree.

`PrivateStateStore` writes dataset-class metadata, source records, complete
snapshot manifests, update checkpoints, and immutable change events
atomically. Failed retrievals leave prior complete records in place.
Reviewed record floors, retained fractions, growth bounds, and freshness
thresholds stop suspicious source results before they can replace complete
state.

The publication builder reads real state, applies quality gates, resolves exact
and reviewed organization identities, applies reviewed relationship decisions,
and writes a temporary minimised publication. Astro statically renders summary,
paginated relationship-directory, and bounded detail pages. It publishes a
compact facet and hex-encoded trigram Bloom manifest plus source/year JSON
partitions capped at 250 records. The browser fetches false-positive-safe
candidate partitions only after filtering; there is no runtime API.

Alias and relationship review catalogues are private operational inputs under
`BREACHGAZETTE_DATA_ROOT/reviews`. They are validated before publication and
are never committed with the public source tree.

```text
official sources -> fixed clients -> source contracts -> private state repository
                                             |
                                             v
health + quality + privacy -> minimised publication -> audited static tree -> Netlify
```

Production and fixture paths are explicit and incompatible. Repository
fixtures cannot be promoted into production output. Netlify is a publication
target, not a durable store; it receives neither the private data root nor
review catalogues.

The same candidate transaction serves the local CLI and scheduled workflow. It
promotes only after update, health report, quality report, publication build,
public-tree audit, compaction, and size checks pass. The candidate swap
preserves private repository metadata and rolls back a failed promotion.
Schedule execution is additionally gated by an explicit repository variable.
