# Threat model

## Assets

Assets include private source caches, normalized production state, observation
history, publication integrity, source attribution, and legal-status accuracy.

## Threats and controls

- **Server-side request forgery:** no arbitrary URLs; exact HTTPS origins,
  paths, redirects, content types, deadlines, pages, rows, and bytes.
- **Source compromise or drift:** exact schemas and markers; reviewed count
  floors, retained fractions, growth bounds, freshness windows, and failed
  checkpoints stop publication.
- **Hostile text:** normalization, escaped Astro rendering, safe URLs, CSP,
  no-referrer, and audits for markup, scripts, controls, bidi characters, and
  formula prefixes.
- **Privacy leakage:** allowlisted organization-level contracts; no victim,
  contact, credential, narrative, letter, attachment, or complete-decision
  fields.
- **Semantic harm:** aggregate and named records are separate; entity roles are
  explicit; allegations cannot become findings; candidate links are not merges.
- **Supply chain:** pinned locks, audit gates, immutable action SHAs, and least
  workflow permissions.
- **Scheduled-state corruption:** schedule enablement is explicit; updates run
  in a candidate copy; only a fully verified candidate can replace and commit
  private state.
- **Fixture contamination:** private-root dataset marker and production
  publication refusal.

The model does not claim that an official source is correct or complete. It
controls how source claims are retrieved, represented, and published.
