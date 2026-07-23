# Architecture

Breach Gazette is a local-first pipeline and a static publication.

Fixed source adapters retrieve bounded official data through a shared hardened
transport. Pydantic contracts preserve provenance and distinguish aggregate,
notification, and regulatory records. Privacy auditing runs before normalized
state, before publication, and against the built tree.

`PrivateStateStore` writes dataset-class metadata, source records, complete
snapshot manifests, update checkpoints, and immutable change events
atomically. Failed retrievals leave prior complete records in place.

The publication builder reads real state, applies quality gates, resolves exact
organization identities, derives conservative relationship candidates, and
writes a temporary minimised publication. Astro statically renders summary and
bounded detail pages. The complete bounded notification dataset is a static
JSON endpoint for browser-local filtering; there is no runtime API.

```text
official sources -> fixed clients -> source contracts -> private state
                                             |
                                             v
quality + privacy -> minimised publication -> Astro static site
```

Production and fixture paths are explicit and incompatible. Repository
fixtures cannot be promoted into production output.
