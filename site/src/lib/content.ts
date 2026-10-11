export const informationPages = {
  methodology: {
    title: "Methodology",
    intro: "How records get here, what their dates and names mean, and what the sources cannot tell us.",
    sections: [
      ["Start with the source", "Each record includes its regulator, reporting scheme, threshold, coverage, named role, revision and source link. A notification count is not necessarily a count of unique incidents."],
      ["Four kinds of record", "Statistics and anonymous report summaries contain no named organisations. Named notifications and regulator actions have their own record types and views. They are not added together as a breach total."],
      ["Dates are not interchangeable", "When something happened, when it was discovered, when it was reported and when it was published can all differ. Breach Gazette also records when it observed a source. Changes to collected records are recorded separately."],
      ["Chronology exclusions", "The reviewed California rule excludes an occurrence date from normalised uses when it follows regulator submission, while retaining the raw source value. Other sources do not inherit this rule."],
      ["Candidate date evidence", "Candidates require an exact organisation-name match, different sources, and an identical published calendar date. Date meanings may differ. This is not interval matching or proof of one incident."],
      ["Cross-country comparisons", "Breach Gazette compares like-for-like measures only when thresholds, periods, population scopes, and units are displayed. It does not publish a generic country ranking."],
    ],
  },
  "entity-resolution": {
    title: "Entity-resolution methodology",
    intro: "How organisation names are matched, and why similar names are often left apart.",
    sections: [
      ["Exact names and reviewed aliases", "Automatic matching is limited to consistent changes in spacing, case, punctuation and reviewed legal suffixes. Similar names may prompt a private review, but similarity alone never joins identities."],
      ["A name is not a role", "A notifying entity, public-sector agency, covered entity, business associate and respondent are different roles. Those distinctions remain even when the records share an organisation profile."],
      ["Reviewed decisions", "Approved or rejected alias decisions retain a stable ID, supporting source set, evidence, date, and review note. The current reviewed alias mapping applies globally, not only to the supporting sources. Chains and cycles are rejected."],
      ["What is not inferred", "Parent and subsidiary relationships, brands, renamed companies, and near-matching names remain separate without reviewed evidence."],
    ],
  },
  "data-quality": {
    title: "Data quality",
    intro: "Checks that must pass before publication, and the limits of those checks.",
    sections: [
      ["When publication stops", "Publication is blocked if a required source is missing, empty or too old, if record-count changes exceed reviewed limits, or if identifiers, source attribution or legal status cannot be validated. Privacy checks must pass too."],
      ["What a pass means", "A passing report means the collected data and public output met the project’s checks. It does not establish that an official source is complete or that an event occurred as reported."],
    ],
  },
  "correction-process": {
    title: "Correction process",
    intro: "If a record is wrong, the correction should be traceable to its source.",
    sections: [
      ["Report", "Use the repository’s private security channel for sensitive concerns. For public data corrections, provide the official source URL, record identifier, and the field believed to be represented incorrectly."],
      ["Review", "A correction is checked against the current official source and source policy. Curated aliases and regulatory manifests require explicit review."],
      ["Publish", "Changes receive version and observation records, so readers can follow what changed. Earlier observations are not silently rewritten."],
    ],
  },
  privacy: {
    title: "Privacy",
    intro: "This is a register of official reporting, not a search tool for exposed personal information.",
    sections: [
      ["What the site does not collect", "There are no accounts, cookies, analytics, remote fonts, query telemetry or background polling. Search and filters run in your browser against static files."],
      ["What the host can see", "Search terms in the address fragment are not sent in HTTP requests. Requests for source and year data files can still reveal access patterns in hosting logs. The search indexes are derived from public records; they are not encryption or a confidentiality guarantee."],
      ["What is left out", "Public files exclude personal emails, phone numbers, street addresses, personal identifiers, credentials, full breach notices, full decisions, free-text narratives and raw combinations of CNIL row values."],
      ["Private state", "Raw retrievals, caches, comparison state, and complete source snapshots remain in a configured private data root outside the repository and deployed site."],
    ],
  },
  security: {
    title: "Security",
    intro: "The public site serves static files. Source material still needs checking, even when it comes from a regulator.",
    sections: [
      ["Limited retrieval", "Each source client has approved HTTPS addresses, expected data structures, limits on pages and bytes, and timeouts. Redirects and content types are checked before data is accepted."],
      ["Publication checks", "Text is escaped, links are validated and privacy audits run before publication. A restrictive content security policy limits what the page can load, and links do not send referrer information."],
      ["Static delivery", "There is no public submission form, victim search, breach-letter retrieval, runtime database or application server."],
    ],
  },
  "legal-and-licensing": {
    title: "Legal and licensing",
    intro: "The project’s MIT licence does not relicense official source material.",
    sections: [
      ["Attribution", "OAIC and NSW IPC materials retain their official attribution and source links. Washington, California, and Massachusetts material remains subject to each government source’s terms and documented conditions. CNIL grouped metrics retain CNIL attribution and the Open Licence 2.0 boundary."],
      ["Annual statistics", "Irish annual figures retain the DPC's valid-notification definition and reuse conditions. The French annual headline retains CNIL's source-defined adjustment and is not added to anonymous grouped counts."],
      ["Regulatory publications", "UK decision records retain publication titles, dates and attribution under the Open Government Licence v3.0. French records retain factual decision metadata and original summaries, not adapted CNIL article text. CNIL's article terms are distinct from its open-data licence. Each source policy records the applicable boundary."],
      ["Legal status", "Investigations, allegations, enforceable undertakings, administrative fines, determinations, judgments and orders are not interchangeable. A regulator-issued fine is not a court judgment or proof that no appeal is possible."],
      ["Logos and marks", "No regulator logos or source images are reproduced. Organization and regulator names identify source records and may be trademarks of their owners."],
    ],
  },
  limitations: {
    title: "Limitations",
    intro: "A record can tell you what was reported. It cannot tell you everything that happened.",
    sections: [
      ["Not a complete census", "Official registers have different reporting thresholds, publication windows, revision practices and named roles. Records can disappear from rolling public windows. This site is not a security rating or a complete list of breaches."],
      ["No independent verification", "Breach Gazette does not independently verify events, causation, population counts, remediation, or compliance."],
      ["Candidate links", "Cross-source links begin as evidence-backed candidates. Reviewed confirmations still preserve every source record and do not establish legal or factual identity beyond the displayed evidence."],
    ],
  },
  "official-response-resources": {
    title: "Official response resources",
    intro: "For an active incident or suspected exposure, go to the organisation concerned and the relevant official guidance.",
    sections: [
      ["Australia", "Contact the affected organization through a verified official channel. For identity and cyber guidance, consult the Australian Cyber Security Centre and IDCARE directly."],
      ["United States", "Contact the notifying organization through its verified official site. Use the relevant state attorney general, HHS OCR, or federal identity-theft resources for authoritative next steps."],
      ["France", "Contact the relevant organization through a verified official channel. Use CNIL and official French cyber-security guidance for authoritative rights and response information."],
      ["Immediate safety", "Do not use Breach Gazette as an emergency service, victim lookup, eligibility check, or notification channel."],
    ],
  },
} as const;
