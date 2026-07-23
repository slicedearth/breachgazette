# Dependency policy

Python has a 3.12 compatibility floor and fully pinned `requirements.lock`.
The editable project install uses `--no-deps --no-build-isolation`. npm uses a committed lockfile
and `npm ci --ignore-scripts`.

Dependencies are selected for a concrete source, validation, document parsing,
testing, or static-build need. Runtime services, production databases,
telemetry libraries, remote fonts, and generic scraping frameworks are
excluded.

CI runs `pip-audit -r requirements.lock` and
`npm audit --audit-level=high`. A high or critical finding blocks release until
removed, upgraded, or documented with reachability and compensating controls.
Lock updates require the full deterministic test, static build, browser, and
public-output audit suite.
