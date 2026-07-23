# Contributing

Changes should preserve the source, legal, privacy, and static-deployment
boundaries described in the methodology.

Before changing a source adapter, update its policy and tests with a
deterministic synthetic fixture. Never add an arbitrary URL, generic scraper,
victim search, breach-letter retrieval, or source credentials. Do not commit
real production state or raw source caches.

Run:

```bash
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest --cov=breachgazette --cov-report=term-missing --cov-fail-under=80
.venv/bin/pip-audit -r requirements.lock
cd site
npm ci --ignore-scripts
npm run check
npm run build:test
npm audit --audit-level=high
npm run test:e2e
```

Pull requests should explain source semantics, privacy impact, legal-status
impact, schema compatibility, and verification. Source-policy and curated
alias changes require review against the linked official source.
