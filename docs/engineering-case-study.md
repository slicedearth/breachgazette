# Engineering case study

Breach Gazette turns heterogeneous official publications into one observatory
without pretending they are one homogeneous breach feed.

The main challenge is semantic rather than syntactic. OAIC publishes aggregate
reporting cells, NSW publishes both a sector snapshot and a selective rolling
register, state attorneys general publish thresholded notification lists, and
OAIC regulatory pages describe procedural and court events. Separate contracts
keep those meanings intact.

Legal-status modelling rejects an ambiguous status and prevents a civil filing
from becoming a finding. Privacy minimization uses narrow fields and multiple
audits instead of collecting complete pages and deleting them later. Exact
entity resolution avoids attractive but harmful fuzzy merges. Temporal event
sourcing records source corrections without asserting why they occurred.

The static publication design removes a runtime server, account database,
query log, and submission attack surface. Quality gates tie deployment to real
data, required complete sources, explicit attribution, legal status, privacy
safety, output bounds, and fixture isolation.

Rejected alternatives included a generic web scraper, browser automation for
the HHS portal, letter retrieval, complete decision storage, probabilistic
entity resolution, a single blended breach feed, incident counts inferred from
notifications, security scores, and unattended source schedules. Each would
weaken provenance, privacy, determinism, or legal accuracy.
