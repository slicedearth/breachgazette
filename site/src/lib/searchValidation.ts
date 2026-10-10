import type { SearchFacets, SearchManifest, SearchPartition } from "./types";

export const FACET_NAMES: Array<keyof SearchFacets> = [
  "jurisdictions",
  "regulators",
  "sources",
  "years",
  "causes",
  "information_categories",
  "population_bands",
  "roles",
  "publication_levels",
];
const object = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);
const integer = (value: unknown, min: number, max: number): value is number =>
  Number.isInteger(value) &&
  (value as number) >= min &&
  (value as number) <= max;
const strings = (value: unknown): value is string[] =>
  Array.isArray(value) &&
  value.length <= 100_000 &&
  value.every((item) => typeof item === "string" && item.length <= 500);
const facets = (value: unknown) =>
  object(value) && FACET_NAMES.every((key) => strings(value[key]));
export function validateSearchManifest(value: unknown): SearchManifest {
  if (
    !object(value) ||
    value.schema_version !== "1.0" ||
    !integer(value.record_count, 0, 1_000_000) ||
    !integer(value.partition_size, 1, 250) ||
    !integer(value.partition_max_bytes, 1, 1_000_000) ||
    !facets(value.facets) ||
    !object(value.facet_counts) ||
    !object(value.query_routing) ||
    value.query_routing.algorithm !== "normalized_trigram_bloom" ||
    value.query_routing.encoding !== "hex" ||
    !integer(value.query_routing.bits, 8, 65536) ||
    value.query_routing.bits % 8 !== 0 ||
    !integer(value.query_routing.hashes, 1, 8) ||
    value.query_routing.minimum_query_length !== 3 ||
    !Array.isArray(value.partitions) ||
    value.partitions.length > 4000
  )
    throw new Error("Search manifest is invalid.");
  const manifest = value as unknown as SearchManifest;
  if (
    FACET_NAMES.some(
      (key) =>
        !object(manifest.facet_counts[key]) ||
        Object.values(manifest.facet_counts[key]).some(
          (count) => !integer(count, 1, manifest.record_count),
        ),
    )
  )
    throw new Error("Search facets are invalid.");
  const ids = new Set<string>();
  let total = 0;
  for (const partition of manifest.partitions) {
    if (
      !object(partition) ||
      typeof partition.id !== "string" ||
      !/^[a-z0-9_-]{1,200}$/.test(partition.id) ||
      ids.has(partition.id) ||
      typeof partition.sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(partition.sha256) ||
      partition.asset !== `${partition.id}-${partition.sha256.slice(0, 16)}` ||
      !integer(partition.count, 1, manifest.partition_size) ||
      !integer(partition.bytes, 1, manifest.partition_max_bytes) ||
      typeof partition.query_bloom !== "string" ||
      !/^[0-9a-f]+$/.test(partition.query_bloom) ||
      partition.query_bloom.length !== manifest.query_routing.bits / 4 ||
      !facets(partition)
    )
      throw new Error("Search partition metadata is invalid.");
    ids.add(partition.id);
    total += partition.count;
  }
  if (total !== manifest.record_count)
    throw new Error("Search manifest count is inconsistent.");
  return manifest;
}
export function validateSearchPartition(
  value: unknown,
  id: string,
  count: number,
): SearchPartition {
  if (
    !object(value) ||
    value.schema_version !== "1.0" ||
    value.partition_id !== id ||
    !Array.isArray(value.records) ||
    value.records.length !== count
  )
    throw new Error("Search partition is invalid.");
  const identities = new Set<string>();
  for (const record of value.records) {
    if (
      !object(record) ||
      typeof record.source_record_id !== "string" ||
      identities.has(record.source_record_id) ||
      ![
        "source_id",
        "jurisdiction",
        "regulator",
        "reporting_scheme",
        "publication_level",
        "coverage_type",
        "source_url",
        "source_revision",
        "source_completeness",
        "local_first_observed_time",
        "local_last_observed_time",
      ].every((key) => typeof record[key] === "string") ||
      !object(record.named_entity) ||
      typeof record.named_entity.source_name !== "string" ||
      typeof record.named_entity.role !== "string" ||
      !Array.isArray(record.dates) ||
      record.dates.some(
        (date) =>
          !object(date) ||
          typeof date.meaning !== "string" ||
          (date.normalized_date !== null &&
            (typeof date.normalized_date !== "string" ||
              !/^\d{4}-\d{2}-\d{2}$/.test(date.normalized_date))),
      ) ||
      !Array.isArray(record.information_categories) ||
      record.information_categories.some(
        (item) => !object(item) || typeof item.normalized_label !== "string",
      ) ||
      !strings(record.limitations)
    )
      throw new Error("Search record is invalid.");
    identities.add(record.source_record_id);
  }
  return value as unknown as SearchPartition;
}
export async function boundedResponseBytes(
  response: Response,
  maxBytes: number,
): Promise<Uint8Array<ArrayBuffer>> {
  if (!response.ok || !response.body)
    throw new Error("Search data is unavailable.");
  const reader = response.body.getReader();
  const parts: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes)
        throw new Error("Search data exceeds its byte budget.");
      parts.push(value);
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    bytes.set(part, offset);
    offset += part.byteLength;
  }
  return bytes;
}
