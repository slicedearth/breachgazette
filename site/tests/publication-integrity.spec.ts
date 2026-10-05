import { expect, test } from "@playwright/test";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { getSearchPartition } from "../src/lib/data";
import { validateSearchManifest } from "../src/lib/searchValidation";

test("build-time loading rejects mismatched generations, shapes and byte budgets", async () => {
  const root = await mkdtemp(join(tmpdir(), "publication-integrity-"));
  const previous = process.env.BREACHGAZETTE_SITE_DATA_DIR;
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
    await rm(root, { recursive: true, force: true });
  }
});
