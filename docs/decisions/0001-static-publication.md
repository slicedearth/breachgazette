# ADR 0001: Publish a static observatory

## Decision

Use a local Python pipeline and Astro static output. Keep production state
outside Git and deploy no runtime database or application server.

## Consequences

Search is browser-local and partitioned, details are bounded, production builds
require a generated real-data directory, and the implemented schedule remains
disabled until an operator explicitly configures its private repository and
enablement variable.
