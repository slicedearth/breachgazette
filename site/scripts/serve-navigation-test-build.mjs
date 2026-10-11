import { createHash } from "node:crypto";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { build, preview } from "astro";

if (process.env.BREACHGAZETTE_TEST_BUILD !== "1") throw new Error("Synthetic navigation builds require test mode.");
const root = new URL("../", import.meta.url);
const fixture = new URL("../../tests/fixtures/site/", import.meta.url);
// Prerendered assets must stay on the build filesystem for atomic renames.
await mkdir(new URL(".astro/", root), { recursive: true });
const temporary = await mkdtemp(fileURLToPath(new URL(".astro/navigation-", root)));
const data = join(temporary, "data");
const read = async (name) => JSON.parse(await readFile(new URL(name, fixture), "utf8"));
const digest = (bytes) => createHash("sha256").update(bytes).digest("hex");
let server;
const stop = async () => { await server?.stop(); await rm(temporary, { recursive: true, force: true }); };
for (const signal of ["SIGINT", "SIGTERM"]) process.once(signal, async () => { await stop(); process.exit(0); });
try {
  await cp(fileURLToPath(fixture), data, { recursive: true });
  const publication = await read("publication.json");
  const aggregateTemplate = publication.aggregates.find((record) => record.source_id === "oaic_ndb");
  publication.aggregates = [
    ...publication.aggregates.filter((record) => record.source_id !== "oaic_ndb"),
    ...Array.from({ length: 305 }, (_, index) => ({ ...aggregateTemplate,
      source_record_id: `fixture-metric-${String(index + 1).padStart(3, "0")}`,
      category: `Example metric ${String(index + 1).padStart(3, "0")}`,
    })),
  ];
  const manifest = await read("search-manifest.json");
  const partition = await read(`search-partitions/${manifest.partitions[0].asset}.json`);
  const records = Array.from({ length: 120 }, (_, index) => {
    const template = partition.records[index % partition.records.length];
    return { ...template, source_record_id: `fixture-navigation-${String(index + 1).padStart(3, "0")}`,
      named_entity: { ...template.named_entity, source_name: `Example Navigation Entity ${String(index + 1).padStart(3, "0")}` },
      has_detail_page: false };
  });
  const body = JSON.stringify({ ...partition, records });
  const metadata = manifest.partitions[0];
  Object.assign(metadata, { count: records.length, bytes: Buffer.byteLength(body), sha256: digest(body) });
  metadata.asset = `${metadata.id}-${metadata.sha256.slice(0, 16)}`;
  manifest.record_count = records.length;
  for (const counts of Object.values(manifest.facet_counts)) {
    for (const key of Object.keys(counts)) counts[key] *= 40;
  }
  const manifestBody = JSON.stringify(manifest);
  publication.manifest.record_counts.notifications = records.length;
  publication.manifest.search_manifest_binding = { schema_version: "1.0", sha256: digest(manifestBody) };
  // Independent synthetic aggregate totals also exercise the front-page layout at scale.
  Object.assign(publication.stats, { public_notifications: records.length,
    anonymized_notification_rows: 100000, aggregate_metrics: 125000, regulatory_actions: 999999 });
  await mkdir(join(data, "search-partitions"), { recursive: true });
  await writeFile(join(data, "search-partitions", `${metadata.asset}.json`), body);
  await writeFile(join(data, "search-manifest.json"), manifestBody);
  await writeFile(join(data, "publication.json"), JSON.stringify(publication));
  process.env.BREACHGAZETTE_SITE_DATA_DIR = data;
  const config = { root: fileURLToPath(root), outDir: join(temporary, "dist"),
    cacheDir: join(temporary, "cache"), logLevel: "error" };
  await build(config);
  server = await preview({ ...config, server: { host: "127.0.0.1", port: 41735 } });
} catch (error) {
  await stop();
  throw error;
}
