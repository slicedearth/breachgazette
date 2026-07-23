# ADR 0001: Publish a static observatory

## Decision

Use a local Python pipeline and Astro static output. Keep production state
outside Git and deploy no runtime database or application server.

## Consequences

Search is browser-local, details are bounded, production builds require a
generated real-data directory, and scheduled updates are not enabled by
default.
