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
organization identities, derives conservative relationship candidates, and
writes a temporary minimised publication. Astro statically renders summary and
bounded detail pages. It publishes a compact search manifest plus source/year
JSON partitions capped at 250 records. The browser fetches candidate partitions
only after filtering; there is no runtime API.

```text
official sources -> fixed clients -> source contracts -> private state
                                             |
                                             v
health + quality + privacy -> minimised publication -> Astro static site
```

Production and fixture paths are explicit and incompatible. Repository
fixtures cannot be promoted into production output.

The scheduled workflow uses a candidate copy of the separate private state
repository. It promotes that candidate only after the update, health report,
quality report, publication build, and public-tree audit all pass. Schedule
execution is additionally gated by an explicit repository variable.
