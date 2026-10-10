import { expect, test } from "@playwright/test";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { getPublication, getSearchManifestJSON, getSearchPartition } from "../src/lib/data";
import { validateSearchManifest } from "../src/lib/searchValidation";

test("build-time loading rejects mismatched generations, shapes and byte budgets", async () => {
  const root = await mkdtemp(join(tmpdir(), "publication-integrity-"));
  const previous = process.env.BREACHGAZETTE_SITE_DATA_DIR;
  const previousTest = process.env.BREACHGAZETTE_TEST_BUILD;
  const manifest = JSON.parse(
    await readFile("../tests/fixtures/site/search-manifest.json", "utf8"),
  );
  const metadata = manifest.partitions[0];
  const original = await readFile(
    `../tests/fixtures/site/search-partitions/${metadata.asset}.json`,
    "utf8",
  );
  try {
    process.env.BREACHGAZETTE_SITE_DATA_DIR = root;
    process.env.BREACHGAZETTE_TEST_BUILD = "1";
    await writeFile(join(root, "publication.json"), await readFile("../tests/fixtures/site/publication.json"));
    await mkdir(join(root, "search-partitions"));
    await writeFile(
      join(root, "search-manifest.json"),
      JSON.stringify(manifest),
    );
    const partitionPath = join(
      root,
      "search-partitions",
      `${metadata.asset}.json`,
    );
    const mismatched = JSON.parse(original);
    const name = mismatched.records[0].named_entity.source_name;
    mismatched.records[0].named_entity.source_name = `X${name.slice(1)}`;
    await writeFile(partitionPath, JSON.stringify(mismatched));
    expect(() => getSearchPartition(metadata.id)).toThrow(/integrity/);
    await writeFile(
      partitionPath,
      JSON.stringify({ ...JSON.parse(original), schema_version: "9.0" }),
    );
    expect(() => getSearchPartition(metadata.id)).toThrow(/invalid/);
    await writeFile(
      partitionPath,
      `${original}${" ".repeat(manifest.partition_max_bytes)}`,
    );
    expect(() => getSearchPartition(metadata.id)).toThrow(/byte budget/);
    expect(() =>
      validateSearchManifest({
        ...manifest,
        record_count: manifest.record_count + 1,
      }),
    ).toThrow(/inconsistent/);
    expect(() =>
      validateSearchManifest({
        ...manifest,
        partitions: [...manifest.partitions, metadata],
      }),
    ).toThrow(/invalid/);
    await writeFile(partitionPath, original);
    expect(getSearchPartition(metadata.id).records).toHaveLength(
      metadata.count,
    );
  } finally {
    if (previous === undefined) delete process.env.BREACHGAZETTE_SITE_DATA_DIR;
    else process.env.BREACHGAZETTE_SITE_DATA_DIR = previous;
    if (previousTest === undefined) delete process.env.BREACHGAZETTE_TEST_BUILD;
    else process.env.BREACHGAZETTE_TEST_BUILD = previousTest;
    await rm(root, { recursive: true, force: true });
  }
});

test("same-count summaries and manifests from different generations are rejected", async () => {
  const root = await mkdtemp(join(tmpdir(), "publication-binding-"));
  const previous = process.env.BREACHGAZETTE_SITE_DATA_DIR;
  const previousTest = process.env.BREACHGAZETTE_TEST_BUILD;
  const publication = JSON.parse(await readFile("../tests/fixtures/site/publication.json", "utf8"));
  const original = await readFile("../tests/fixtures/site/search-manifest.json", "utf8");
  const other = JSON.parse(original);
  other.generated_at = "2026-02-02T00:00:00Z";
  const digest = createHash("sha256").update(original).digest("hex");
  try {
    process.env.BREACHGAZETTE_SITE_DATA_DIR = root;
    process.env.BREACHGAZETTE_TEST_BUILD = "1";
    publication.manifest.search_manifest_binding = { schema_version: "1.0", sha256: digest };
    await writeFile(join(root, "publication.json"), JSON.stringify(publication));
    await writeFile(join(root, "search-manifest.json"), JSON.stringify(other));
    expect(other.record_count).toBe(publication.manifest.record_counts.notifications);
    expect(() => getPublication()).toThrow(/generation/);
    await writeFile(join(root, "search-manifest.json"), original);
    expect(getPublication().manifest.search_manifest_binding?.sha256).toBe(digest);
    expect(getSearchManifestJSON()).toBe(original);
  } finally {
    if (previous === undefined) delete process.env.BREACHGAZETTE_SITE_DATA_DIR;
    else process.env.BREACHGAZETTE_SITE_DATA_DIR = previous;
    if (previousTest === undefined) delete process.env.BREACHGAZETTE_TEST_BUILD;
    else process.env.BREACHGAZETTE_TEST_BUILD = previousTest;
    await rm(root, { recursive: true, force: true });
  }
});

for (const matching of [true, false]) {
  test(`browser publication binding ${matching ? "accepts its own" : "rejects a different"} manifest`, async ({ page }) => {
    const original = await readFile("../tests/fixtures/site/search-manifest.json", "utf8");
    const digest = createHash("sha256").update(original).digest("hex");
    await page.route("**/latest/", async (route) => {
      const response = await route.fetch();
      const html = (await response.text()).replace(/data-manifest-checksum(?:="[^"]*")?/, `data-manifest-checksum="${digest}"`);
      expect(html).toContain(`data-manifest-checksum="${digest}"`);
      await route.fulfill({ response, body: html });
    });
    const other = JSON.parse(original);
    other.generated_at = "2026-02-02T00:00:00Z";
    await page.route("**/data/notifications/manifest.json", (route) => route.fulfill({
      contentType: "application/json", body: matching ? original : JSON.stringify(other),
    }));
    await page.goto("/latest/");
    if (matching) {
      await expect(page.locator("[data-result-count]")).toContainText("published source records");
      await expect(page.locator("[data-search-retry]")).toBeHidden();
    } else {
      await expect(page.locator("[data-result-count]")).toContainText("could not be loaded");
      await expect(page.locator("[data-search-retry]")).toBeVisible();
      await expect(page.locator("[data-export-results]")).toBeDisabled();
      await expect(page.locator("[data-results] table")).toBeVisible();
    }
  });
}
