# Dependency policy

Python has a 3.12 compatibility floor and fully pinned `requirements.lock`.
The editable project install uses `--no-deps --no-build-isolation`. npm uses a committed lockfile
and `npm ci --ignore-scripts --no-audit` in automation. A separate, explicit
audit step keeps the vulnerability gate fail-closed without repeating the same
registry request during installation.

The Python lock is generated in an isolated Python 3.12 environment with pip
26.1.2. Regenerate it with `.venv/bin/python scripts/lock_python.py`, or verify
the active environment against it with
`.venv/bin/python scripts/lock_python.py --check-installed`. The command checks
that every build, runtime, and development dependency declared in
`pyproject.toml` remains exactly pinned.

Dependencies are selected for a concrete source, validation, document parsing,
testing, or static-build need. Runtime services, production databases,
telemetry libraries, remote fonts, and generic scraping frameworks are
excluded.

CI runs `pip-audit -r requirements.lock` and
`npm audit --audit-level=high`. A high or critical finding blocks release until
removed, upgraded, or documented with reachability and compensating controls.
Lock updates require the full deterministic test, static build, browser, and
public-output audit suite.

Cross-browser CI uses the official Playwright container pinned by immutable
digest. Its image tag must match the exact `@playwright/test` version; a
security test enforces that pairing whenever the dependency changes.
