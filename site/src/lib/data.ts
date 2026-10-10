import { readFileSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  validateSearchManifest,
  validateSearchPartition,
} from "./searchValidation";
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
  return isAbsolute(configured)
    ? configured
    : resolve(process.cwd(), configured);
}

function readJson<T>(name: string, maxBytes = 60_000_000): T {
  const path = join(dataDirectory(), name);
  if (statSync(path).size > maxBytes)
    throw new Error("Publication input exceeds its byte budget");
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

let publicationCache: Publication | undefined;
let cacheDirectory: string | undefined;
let searchManifestText: string | undefined;

function ensureDataDirectory(): void {
  const directory = dataDirectory();
  if (cacheDirectory === directory) return;
  cacheDirectory = directory;
  publicationCache = undefined;
  searchManifestCache = undefined;
  searchManifestText = undefined;
  searchPartitionCache.clear();
  notificationCache = undefined;
}

export function getPublication(): Publication {
  ensureDataDirectory();
  if (publicationCache) return publicationCache;
  const publication = readJson<Publication>("publication.json");
  const datasetClass = publication.manifest?.dataset_class;
  const testBuild = process.env.BREACHGAZETTE_TEST_BUILD === "1";
  if (
    datasetClass !== "real_source_data" &&
    !(testBuild && datasetClass === "test_fixture")
  ) {
    throw new Error("Production site builds require real_source_data");
  }
  if (!publication.quality?.passed) {
    throw new Error("Publication quality report did not pass");
  }
  const path = join(dataDirectory(), "search-manifest.json");
  if (statSync(path).size > 5_000_000) throw new Error("Search manifest exceeds its byte budget");
  const bytes = readFileSync(path);
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  const manifest = validateSearchManifest(JSON.parse(text));
  const binding = publication.manifest.search_manifest_binding;
  if (binding != null && (
    binding.schema_version !== "1.0" || typeof binding.sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(binding.sha256) ||
    createHash("sha256").update(bytes).digest("hex") !== binding.sha256
  )) throw new Error("Search manifest does not belong to this publication generation");
  if (manifest.record_count !== publication.manifest.record_counts.notifications) {
    throw new Error("Publication and search manifest counts disagree");
  }
  searchManifestCache = manifest;
  searchManifestText = text;
  publicationCache = publication;
  return publicationCache;
}

let searchManifestCache: SearchManifest | undefined;

export function getSearchManifest(): SearchManifest {
  getPublication();
  return searchManifestCache!;
}

export function getSearchManifestJSON(): string {
  getPublication();
  return searchManifestText!;
}

const searchPartitionCache = new Map<string, SearchPartition>();

export function getSearchPartition(id: string): SearchPartition {
  ensureDataDirectory();
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
  const partition = validateSearchPartition(
    readJson<unknown>(
      join("search-partitions", `${metadata.asset}.json`),
      manifest.partition_max_bytes + 1,
    ),
    id,
    metadata.count,
  );
  const encoded = Buffer.from(JSON.stringify(partition), "utf8");
  if (
    encoded.length !== metadata.bytes ||
    createHash("sha256").update(encoded).digest("hex") !== metadata.sha256
  ) {
    throw new Error("search partition failed build-time integrity validation");
  }
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
  return (
    notification.dates
      .map((item) => item.normalized_date)
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) ?? "0001-01-01"
  );
}

export function getAllNotifications(): Notification[] {
  ensureDataDirectory();
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
  notificationCache = notifications.sort(
    (left, right) =>
      latestSourceDate(right).localeCompare(latestSourceDate(left)) ||
      right.source_record_id.localeCompare(left.source_record_id),
  );
  return notificationCache;
}
