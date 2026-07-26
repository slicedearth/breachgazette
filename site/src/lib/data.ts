import { readFileSync } from "node:fs";
import { isAbsolute, join, resolve } from "node:path";
import type {
  Notification,
  Publication,
  SearchManifest,
  SearchPartition,
} from "./types";

function dataDirectory(): string {
  const configured = process.env.BREACHGAZETTE_SITE_DATA_DIR;
  if (!configured) {
    throw new Error("BREACHGAZETTE_SITE_DATA_DIR is required");
  }
  return isAbsolute(configured) ? configured : resolve(process.cwd(), configured);
}

function readJson<T>(name: string): T {
  const path = join(dataDirectory(), name);
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

let publicationCache: Publication | undefined;

export function getPublication(): Publication {
  if (publicationCache) return publicationCache;
  const publication = readJson<Publication>("publication.json");
  const datasetClass = publication.manifest?.dataset_class;
  const testBuild = process.env.BREACHGAZETTE_TEST_BUILD === "1";
  if (datasetClass !== "real_source_data" && !(testBuild && datasetClass === "test_fixture")) {
    throw new Error("Production site builds require real_source_data");
  }
  if (!publication.quality?.passed) {
    throw new Error("Publication quality report did not pass");
  }
  publicationCache = publication;
  return publicationCache;
}

let searchManifestCache: SearchManifest | undefined;

export function getSearchManifest(): SearchManifest {
  if (searchManifestCache) return searchManifestCache;
  const manifest = readJson<SearchManifest>("search-manifest.json");
  const facetNames = [
    "jurisdictions",
    "regulators",
    "sources",
    "years",
    "causes",
    "information_categories",
    "population_bands",
    "roles",
    "publication_levels",
  ] as const;
  if (
    !manifest ||
    !Array.isArray(manifest.partitions) ||
    !Number.isInteger(manifest.record_count) ||
    !manifest.facets ||
    !manifest.facet_counts ||
    facetNames.some(
      (facet) =>
        !Array.isArray(manifest.facets[facet]) ||
        typeof manifest.facet_counts[facet] !== "object" ||
        manifest.facet_counts[facet] === null ||
        Object.values(manifest.facet_counts[facet]).some(
          (count) => !Number.isInteger(count) || count < 1,
        ),
    ) ||
    manifest.query_routing?.algorithm !== "normalized_trigram_bloom" ||
    manifest.query_routing?.encoding !== "hex" ||
    !Number.isInteger(manifest.query_routing.bits) ||
    !Number.isInteger(manifest.query_routing.hashes) ||
    !Number.isInteger(manifest.partition_max_bytes) ||
    manifest.partition_max_bytes <= 0 ||
    manifest.partitions.some(
      (partition) =>
        partition.asset !== `${partition.id}-${partition.sha256.slice(0, 16)}` ||
        !/^[a-z0-9_-]+-[0-9a-f]{16}$/.test(partition.asset) ||
        !partition.query_bloom ||
        !Number.isInteger(partition.bytes) ||
        partition.bytes <= 0 ||
        partition.bytes > manifest.partition_max_bytes ||
        !/^[0-9a-f]{64}$/.test(partition.sha256),
    )
  ) {
    throw new Error("search-manifest.json is invalid");
  }
  searchManifestCache = manifest;
  return searchManifestCache;
}

const searchPartitionCache = new Map<string, SearchPartition>();

export function getSearchPartition(id: string): SearchPartition {
  const cached = searchPartitionCache.get(id);
  if (cached) return cached;
  if (!/^[a-z0-9_-]+$/.test(id)) {
    throw new Error("search partition id is invalid");
  }
  const manifest = getSearchManifest();
  const metadata = manifest.partitions.find((partition) => partition.id === id);
  if (!metadata) {
    throw new Error("search partition id is not declared");
  }
  const partition = readJson<SearchPartition>(
    join("search-partitions", `${metadata.asset}.json`),
  );
  if (
    partition.partition_id !== id ||
    !Array.isArray(partition.records) ||
    partition.records.length !== metadata.count
  ) {
    throw new Error("search partition payload is invalid");
  }
  searchPartitionCache.set(id, partition);
  return partition;
}

let notificationCache: Notification[] | undefined;

function latestSourceDate(notification: Notification): string {
  return notification.dates
    .map((item) => item.normalized_date)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1) ?? "0001-01-01";
}

export function getAllNotifications(): Notification[] {
  if (notificationCache) return notificationCache;
  const manifest = getSearchManifest();
  const notifications = manifest.partitions.flatMap(
    (partition) => getSearchPartition(partition.id).records,
  );
  if (notifications.length !== manifest.record_count) {
    throw new Error(
      `notification partitions contain ${notifications.length} records; expected ${manifest.record_count}`,
    );
  }
  notificationCache = notifications.sort((left, right) =>
    latestSourceDate(right).localeCompare(latestSourceDate(left))
    || right.source_record_id.localeCompare(left.source_record_id)
  );
  return notificationCache;
}
