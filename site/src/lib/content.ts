export const informationPages = {
  methodology: {
    title: "Methodology",
    intro: "How source semantics, date meanings, organization roles, candidate relationships, and corrections remain explicit.",
    sections: [
      ["Source before synthesis", "Every value retains its regulator, reporting scheme, publication level, threshold, coverage type, source role, revision, and source link. Notification counts are not assumed to equal unique incidents."],
      ["Aggregate versus record", "Aggregate statistics are analytical measures without named organizations. Named notifications and regulatory actions use separate contracts and views."],
      ["Time and change", "Occurrence, awareness, submission, publication, and observation dates retain separate meanings. New source snapshots produce deterministic change events rather than rewriting history silently."],
      ["Cross-country comparisons", "Breach Gazette compares like-for-like measures only when thresholds, periods, population scopes, and units are displayed. It does not publish a generic Australia-versus-US ranking."],
    ],
  },
  "entity-resolution": {
    title: "Entity-resolution methodology",
    intro: "Organization identities are joined only through exact normalized names or reviewed aliases.",
    sections: [
      ["Conservative resolution", "Normalization is deterministic and limited to spacing, case, punctuation, and reviewed legal suffix handling. Similarity creates private proposals only and never creates an identity."],
      ["Source roles remain", "A notifying entity, public-sector agency, covered entity, business associate, and respondent are distinct roles even when they resolve to one organization profile."],
      ["Reviewed decisions", "Approved or rejected alias decisions retain a stable ID, source set, evidence, date, and review note. Chains and cycles are rejected."],
      ["What is not inferred", "Parent and subsidiary relationships, brands, renamed companies, and near-matching names remain separate without reviewed evidence."],
    ],
  },
  "data-quality": {
    title: "Data quality",
    intro: "Publication is fail-closed when required real data, source attribution, legal status, privacy safety, or source schema cannot be established.",
    sections: [
      ["Automated gates", "Required sources must be present and non-empty, snapshots fresh, record-count changes within reviewed bounds, identifiers deterministic, regulatory statuses explicit, and public fields privacy-safe."],
      ["Limits of validation", "A passing report validates the pipeline contract and published representation. It does not establish that an official source is complete or that an underlying event occurred as reported."],
    ],
  },
  "correction-process": {
    title: "Correction process",
    intro: "Corrections preserve both official-source authority and the project’s temporal audit trail.",
    sections: [
      ["Report", "Use the repository’s private security channel for sensitive concerns. For public data corrections, provide the official source URL, record identifier, and the field believed to be represented incorrectly."],
      ["Review", "A correction is checked against the current official source and source policy. Curated aliases and regulatory manifests require explicit review."],
      ["Publish", "Source changes create deterministic version and change records. Breach Gazette does not silently rewrite observed history."],
    ],
  },
  privacy: {
    title: "Privacy",
    intro: "Breach Gazette publishes organization-level official data while excluding victim, contact, credential, and narrative material.",
    sections: [
      ["No visitor profiling", "There are no accounts, cookies, analytics, remote fonts, query telemetry, or background requests. Filters execute locally against static data."],
      ["Minimised records", "The public output excludes personal emails, phone numbers, street addresses, identifiers, credentials, complete breach notices, complete decisions, and free-text narratives."],
      ["Private state", "Raw retrievals, caches, comparison state, and complete source snapshots remain in a configured private data root outside the repository and deployed site."],
    ],
  },
  security: {
    title: "Security",
    intro: "The platform treats official source content as hostile and keeps its public deployment static.",
    sections: [
      ["Fixed source clients", "Clients use allowlisted HTTPS origins and paths, exact schemas, bounded pages and bytes, strict timeouts, redirect validation, and explicit content types."],
      ["Safe publication", "Text is escaped, URLs are validated, privacy audits run at multiple boundaries, and the site uses a restrictive content security policy and no-referrer behavior."],
      ["No submission surface", "There is no public form, victim search, breach-letter retrieval, runtime database, or application server."],
    ],
  },
  "legal-and-licensing": {
    title: "Legal and licensing",
    intro: "The project’s MIT licence does not relicense official source material.",
    sections: [
      ["Attribution", "OAIC and NSW IPC materials retain their official attribution and source links. Washington, California, and Massachusetts material remains subject to each government source’s terms and documented conditions."],
      ["Legal status", "Investigations, allegations, enforceable undertakings, determinations, judgments, and orders are not interchangeable. Each timeline record keeps exact source-backed status."],
      ["Logos and marks", "No regulator logos or source images are reproduced. Organization and regulator names identify source records and may be trademarks of their owners."],
    ],
  },
  limitations: {
    title: "Limitations",
    intro: "Breach Gazette explains published evidence; it is not a complete breach census or a security rating.",
    sections: [
      ["Incomplete by design", "Official registers have different thresholds, windows, revision practices, and named-entity roles. Some records can disappear from rolling public windows."],
      ["No independent verification", "Breach Gazette does not independently verify events, causation, population counts, remediation, or compliance."],
      ["Candidate links", "Cross-source links begin as evidence-backed candidates. Reviewed confirmations still preserve every source record and do not establish legal or factual identity beyond the displayed evidence."],
    ],
  },
  "official-response-resources": {
    title: "Official response resources",
    intro: "For an active incident or suspected exposure, use authoritative organizational and government guidance.",
    sections: [
      ["Australia", "Contact the affected organization through a verified official channel. For identity and cyber guidance, consult the Australian Cyber Security Centre and IDCARE directly."],
      ["United States", "Contact the notifying organization through its verified official site. Use the relevant state attorney general, HHS OCR, or federal identity-theft resources for authoritative next steps."],
      ["Immediate safety", "Do not use Breach Gazette as an emergency service, victim lookup, eligibility check, or notification channel."],
    ],
  },
} as const;
