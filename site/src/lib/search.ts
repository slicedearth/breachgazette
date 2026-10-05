import casefold from "../../../src/breachgazette/publish/search-casefold.json" with { type: "json" };
import type {
  Notification,
  SearchManifest,
  SearchPartitionMetadata,
} from "./types";

export const NORMALIZATION_VERSION =
  "unicode15_casefold_whitespace_codepoint_v1";
const folds: Record<string, string> = casefold;
export const normalizeSearch = (value: string) =>
  Array.from(value, (char) => folds[char] ?? char)
    .join("")
    .replace(
      /[\x09-\x0d\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/g,
      " ",
    )
    .replace(/^ +| +$/g, "");
export const queryTokens = (value: string) =>
  normalizeSearch(value).split(" ").filter(Boolean);
export const trigrams = (value: string) => {
  const points = Array.from(normalizeSearch(value));
  return new Set(
    points
      .slice(0, -2)
      .map((_, index) => points.slice(index, index + 3).join("")),
  );
};
export const searchText = (record: Notification) =>
  normalizeSearch(
    [
      record.named_entity.source_name,
      record.source_record_id,
      record.jurisdiction,
      record.regulator,
      record.reporting_scheme,
      record.named_entity.role,
    ]
      .filter(Boolean)
      .join(" "),
  );
export const populationBand = (record: Notification) => {
  const count = record.affected_population?.count;
  if (count === null || count === undefined) return "not_published";
  if (count === 0) return "zero";
  if (count < 500) return "1_499";
  if (count < 1_000) return "500_999";
  if (count < 10_000) return "1000_9999";
  if (count < 100_000) return "10000_99999";
  return "100000_plus";
};
export type FilterState = Readonly<Record<string, string>>;
export const snapshotFilters = (
  controls: Array<HTMLInputElement | HTMLSelectElement>,
): FilterState =>
  Object.freeze(
    Object.fromEntries(
      controls.map((control) => [control.name, control.value.trim()]),
    ),
  );
const fnv1a = (value: string) => {
  let hash = 2_166_136_261;
  for (const byte of new TextEncoder().encode(value)) {
    hash ^= byte;
    hash = Math.imul(hash, 16_777_619) >>> 0;
  }
  return hash;
};
export function queryMayMatch(
  partition: SearchPartitionMetadata,
  term: string,
  manifest: SearchManifest,
) {
  // Older publications used different Unicode semantics. Never exclude using those bits.
  if (manifest.query_routing.normalization_version !== NORMALIZATION_VERSION)
    return true;
  const bloom = Uint8Array.from(
    partition.query_bloom.match(/.{2}/g) ?? [],
    (pair) => parseInt(pair, 16),
  );
  for (const token of queryTokens(term)) {
    if (Array.from(token).length < manifest.query_routing.minimum_query_length)
      continue;
    for (const gram of trigrams(token)) {
      for (let seed = 0; seed < manifest.query_routing.hashes; seed += 1) {
        const bit = fnv1a(`${seed}|${gram}`) % manifest.query_routing.bits;
        if ((bloom[Math.floor(bit / 8)]! & (1 << (bit % 8))) === 0)
          return false;
      }
    }
  }
  return true;
}
export function matchesPartition(
  partition: SearchPartitionMetadata,
  filters: FilterState,
  manifest: SearchManifest,
) {
  const scalar: Array<[string, keyof SearchPartitionMetadata]> = [
    ["jurisdiction", "jurisdictions"],
    ["regulator", "regulators"],
    ["source", "sources"],
    ["cause", "causes"],
    ["information", "information_categories"],
    ["population", "population_bands"],
    ["role", "roles"],
    ["publication", "publication_levels"],
  ];
  if (
    scalar.some(
      ([name, facet]) =>
        filters[name] &&
        !(
          name === "population" &&
          manifest.query_routing.normalization_version !== NORMALIZATION_VERSION
        ) &&
        !(partition[facet] as string[]).includes(filters[name]!),
    )
  )
    return false;
  // Legacy year facets contain only the latest year, so date pruning is unsafe there.
  if (
    manifest.query_routing.normalization_version === NORMALIZATION_VERSION &&
    (filters.date_from || filters.date_to)
  ) {
    if (
      !partition.years.some(
        (year) =>
          year === "unknown" ||
          ((!filters.date_from || `${year}-12-31` >= filters.date_from) &&
            (!filters.date_to || `${year}-01-01` <= filters.date_to)),
      )
    )
      return false;
  }
  return queryMayMatch(partition, filters.query ?? "", manifest);
}
export function matchesRecord(record: Notification, filters: FilterState) {
  return (
    queryTokens(filters.query ?? "").every((term) =>
      searchText(record).includes(term),
    ) &&
    (!filters.jurisdiction || record.jurisdiction === filters.jurisdiction) &&
    (!filters.regulator || record.regulator === filters.regulator) &&
    (!filters.source || record.source_id === filters.source) &&
    ((!filters.date_from && !filters.date_to) ||
      record.dates.some(
        (item) =>
          Boolean(item.normalized_date) &&
          (!filters.date_from || item.normalized_date! >= filters.date_from) &&
          (!filters.date_to || item.normalized_date! <= filters.date_to),
      )) &&
    (!filters.cause ||
      record.breach_cause?.normalized_label === filters.cause) &&
    (!filters.information ||
      record.information_categories.some(
        (item) => item.normalized_label === filters.information,
      )) &&
    (!filters.population || populationBand(record) === filters.population) &&
    (!filters.role || record.named_entity.role === filters.role) &&
    (!filters.publication || record.publication_level === filters.publication)
  );
}
