import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import type { SearchManifest, SearchPartition } from "../src/lib/types";
import {
  normalizeSearch,
  matchesPartition,
  matchesRecord,
  queryMayMatch,
} from "../src/lib/search";
import { csvCell, notificationCsv } from "../src/lib/searchExport";

const golden = JSON.parse(
  await readFile("../tests/fixtures/search-routing.json", "utf8"),
) as {
  manifest: SearchManifest;
  partitions: Record<string, SearchPartition>;
  cases: Array<{ query: string; normalized: string; expected_ids: string[] }>;
  aged: {
    manifest: SearchManifest;
    partitions: Record<string, SearchPartition>;
  };
};

test("supplementary code points enter Bloom routing rather than the short-query fallback", () => {
  const query = "𐐨ex";
  expect(Array.from(normalizeSearch(query))).toHaveLength(3);
  const partition = golden.manifest.partitions.find((item) =>
    golden.partitions[item.asset]!.records.some((record) => matchesRecord(record, { query })),
  )!;
  expect(partition).toBeDefined();
  expect(queryMayMatch(partition, query, golden.manifest)).toBe(true);
  expect(queryMayMatch(
    { ...partition, query_bloom: "00".repeat(golden.manifest.query_routing.bits / 8) },
    query,
    golden.manifest,
  )).toBe(false);
});

for (const entry of ["input", "hash"] as const) {
  test(`invalid dates settle busy state after ${entry} navigation without settling newer work`, async ({ page }) => {
    const gates = [0, 1].map(() => {
      let started!: () => void;
      let release!: () => void;
      let finished!: () => void;
      return {
        requested: new Promise<void>((resolve) => { started = resolve; }),
        held: new Promise<void>((resolve) => { release = resolve; }),
        done: new Promise<void>((resolve) => { finished = resolve; }),
        start: () => started(), unlock: () => release(), finish: () => finished(),
      };
    });
    await page.route("**/data/notifications/manifest.json", (route) =>
      route.fulfill({ json: golden.manifest }),
    );
    await page.route(/\/data\/notifications\/fixture-.*\.json$/, async (route) => {
      const asset = new URL(route.request().url()).pathname.split("/").at(-1)!.slice(0, -5);
      const partition = golden.partitions[asset]!;
      const index = Number(partition.records[0]!.source_record_id.split("-").at(-1));
      const gate = index < 2 ? gates[index]! : undefined;
      if (gate) { gate.start(); await gate.held; }
      try { await route.fulfill({ json: partition }); }
      catch { /* The invalid date render has deliberately aborted superseded fetches. */ }
      finally { gate?.finish(); }
    });
    try {
      await page.goto("/latest/#query=STRASSE");
      await gates[0]!.requested;
      const results = page.locator("[data-results]");
      await expect(results).toHaveAttribute("aria-busy", "true");
      if (entry === "input") {
        await page.locator('[name="date_from"]').fill("2026-02-01");
        await page.locator('[name="date_to"]').fill("2026-01-01");
      } else {
        await page.evaluate(() => {
          location.hash = "query=STRASSE&date_from=2026-02-01&date_to=2026-01-01";
        });
      }
      await expect(page.locator("[data-result-count]")).toHaveText(
        "Source date from must be on or before source date to.",
      );
      await expect(page.locator("[data-export-results]")).toBeDisabled();
      await expect(results).not.toHaveAttribute("aria-busy", "true");
      await expect(results.getByRole("navigation", { name: "Notification pages above results" })).toBeVisible();
      await expect(results.locator(".directory-summary")).toContainText("complete published register");
      await page.evaluate(() => {
        location.hash = "query=%C4%B0STANBUL&date_from=2025-12-01&date_to=2026-01-31";
      });
      await gates[1]!.requested;
      await expect(results).toHaveAttribute("aria-busy", "true");
      gates[0]!.unlock();
      await gates[0]!.done;
      await expect(results).toHaveAttribute("aria-busy", "true");
      gates[1]!.unlock();
      await expect(page.locator("[data-result-count]")).toContainText("1 matching source records");
      await expect(results).toContainText("İstanbul Example");
      await expect(results).not.toHaveAttribute("aria-busy", "true");
      await expect(page.locator("[data-export-results]")).toBeEnabled();
    } finally { for (const gate of gates) gate.unlock(); }
  });
}

test("export retains its field allowlist and neutralises formula prefixes", () => {
  expect(csvCell("=SUM(A1)")).toBe('"\'=SUM(A1)"');
  expect(csvCell('a,b"c')).toBe('"a,b""c"');
  const record = Object.values(golden.partitions)[0]!.records[0]!;
  const csv = notificationCsv([record]);
  expect(csv).not.toContain("source_checksum");
  expect(csv).not.toContain("a".repeat(64));
  expect(csv).toContain(record.source_record_id);
});
async function routeGolden(page: Page, delay = 0) {
  await page.route("**/data/notifications/manifest.json", (route) =>
    route.fulfill({ json: golden.manifest }),
  );
  await page.route(
    /\/data\/notifications\/fixture-.*\.json$/,
    async (route) => {
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
      const asset = new URL(route.request().url()).pathname
        .split("/")
        .at(-1)!
        .slice(0, -5);
      await route.fulfill({ json: golden.partitions[asset] });
    },
  );
}

test("Python routing assets have no false negatives under the browser predicate", async ({
  page,
}) => {
  for (const item of golden.cases) {
    expect(normalizeSearch(item.query)).toBe(item.normalized);
    for (const partition of golden.manifest.partitions) {
      const records = golden.partitions[partition.asset]!.records;
      for (const record of records) {
        if (matchesRecord(record, { query: item.query })) {
          expect(
            matchesPartition(partition, { query: item.query }, golden.manifest),
          ).toBe(true);
        }
      }
    }
  }
  await routeGolden(page);
  await page.goto("/latest/");
  for (const item of golden.cases) {
    await page.locator('[name="query"]').fill(item.query);
    await expect(page.locator("[data-result-count]")).toContainText(
      `${item.expected_ids.length} matching source records`,
    );
    await expect(page.locator("[data-export-results]")).toBeEnabled();
  }
  await page.locator('[name="query"]').fill("");
  await page.locator('[name="date_from"]').fill("2025-12-01");
  await page.locator('[name="date_to"]').fill("2025-12-31");
  await expect(page.locator("[data-result-count]")).toContainText(
    "11 matching source records",
  );
});

test("population bands and export cover every reviewed boundary", async ({
  page,
}) => {
  await routeGolden(page);
  await page.goto("/latest/");
  for (const [band, count] of [
    ["not_published", 1],
    ["zero", 1],
    ["1_499", 2],
    ["500_999", 2],
    ["1000_9999", 2],
    ["10000_99999", 2],
    ["100000_plus", 1],
  ] as const) {
    await page.locator('[name="population"]').selectOption(band);
    await expect(page.locator("[data-result-count]")).toContainText(
      `${count} matching source records`,
    );
  }
});

test("export is invalidated at mutation before the debounce or response", async ({
  page,
}) => {
  await routeGolden(page, 350);
  await page.goto("/latest/#query=STRASSE");
  const exporter = page.locator("[data-export-results]");
  await expect(exporter).toBeEnabled();
  await page.locator('[name="query"]').fill("CAFÉ");
  await expect(exporter).toBeDisabled();
  // Change again inside the debounce interval. Only this state may settle.
  await page.locator('[name="query"]').fill("İSTANBUL");
  await expect(exporter).toBeDisabled();
  await expect(page.locator("[data-results]")).toContainText(
    "İstanbul Example",
  );
  await expect(exporter).toBeEnabled();
  const downloadPromise = page.waitForEvent("download");
  await exporter.click();
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const part of stream!) chunks.push(Buffer.from(part));
  const csv = Buffer.concat(chunks).toString("utf8");
  expect(csv).toContain("İstanbul Example");
  expect(csv).not.toContain("Straße Example");
  expect(csv).not.toContain("CAFÉ Example");
  await page.locator("[data-reset-filters]").click();
  await expect(exporter).toBeDisabled();
  await expect(page.locator("[data-result-count]")).toContainText(
    "no search partitions loaded",
  );
});

test("a stale in-flight partition cannot settle during the input debounce", async ({
  page,
}) => {
  let requested!: () => void;
  let release!: () => void;
  const started = new Promise<void>((resolve) => {
    requested = resolve;
  });
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/data/notifications/manifest.json", (route) =>
    route.fulfill({ json: golden.manifest }),
  );
  await page.route(
    /\/data\/notifications\/fixture-.*\.json$/,
    async (route) => {
      const asset = new URL(route.request().url()).pathname
        .split("/")
        .at(-1)!
        .slice(0, -5);
      const partition = golden.partitions[asset]!;
      if (partition.records[0]!.source_record_id === "fixture-golden-0") {
        requested();
        await delayed;
      }
      await route.fulfill({ json: partition });
    },
  );
  await page.goto("/latest/#query=STRASSE");
  await started;
  await page.locator('[name="query"]').fill("İSTANBUL");
  release();
  await expect(page.locator("[data-export-results]")).toBeDisabled();
  await expect(page.locator("[data-results]")).toContainText(
    "İstanbul Example",
  );
  await expect(page.locator("[data-results]")).not.toContainText(
    "Straße Example",
  );
  await expect(page.locator("[data-export-results]")).toBeEnabled();
});

test("superseded history search cannot steal query focus", async ({ page }) => {
  let requested!: () => void;
  let release!: () => void;
  const started = new Promise<void>((resolve) => { requested = resolve; });
  const delayed = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/data/notifications/manifest.json", (route) =>
    route.fulfill({ json: golden.manifest }),
  );
  await page.route(/\/data\/notifications\/fixture-.*\.json$/, async (route) => {
    const asset = new URL(route.request().url()).pathname.split("/").at(-1)!.slice(0, -5);
    const partition = golden.partitions[asset]!;
    if (partition.records[0]!.source_record_id === "fixture-golden-0") {
      requested();
      await delayed;
    }
    await route.fulfill({ json: partition });
  });
  await page.goto("/latest/#query=İSTANBUL");
  await expect(page.locator("[data-results]")).toContainText("İstanbul Example");
  await page.locator("[data-results] a").first().focus();
  await page.evaluate(() => { window.location.hash = "query=STRASSE"; });
  await started;
  const query = page.locator('[name="query"]');
  await query.fill("İSTANBUL");
  release();
  await expect(page.locator("[data-export-results]")).toBeEnabled();
  await expect(query).toBeFocused();
  await expect(page.locator("[data-results]")).toContainText("İstanbul Example");
});

test("an aborted manifest keeps a recoverable static register", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/data/notifications/manifest.json", (route) =>
    route.abort("aborted"),
  );
  await page.goto("/latest/");
  await expect(page.locator("[data-search-retry]")).toBeVisible();
  await expect(page.locator("[data-results] table")).toBeVisible();
  expect(errors).toEqual([]);
});

for (const [name, body] of [
  ["HTML success", "<html>Not JSON</html>"],
  ["truncated JSON", '{"schema_version":'],
  ["missing facets", JSON.stringify({ ...golden.manifest, facets: null })],
  [
    "unsupported schema",
    JSON.stringify({ ...golden.manifest, schema_version: "9.0" }),
  ],
] as const) {
  test(`invalid manifest: ${name} retains static fallback and retry`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/data/notifications/manifest.json", (route) =>
      route.fulfill({ body, contentType: "application/json" }),
    );
    await page.goto("/latest/");
    await expect(page.locator("[data-result-count]")).toContainText(
      "manifest could not be loaded",
    );
    await expect(page.locator("[data-search-retry]")).toBeVisible();
    await expect(page.locator("[data-results] table")).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test("old notification bookmarks retain a route to the existing viewer", async ({
  page,
}) => {
  expect(golden.aged.manifest.record_count).toBe(252);
  const old = Object.values(golden.aged.partitions)
    .flatMap((partition) => partition.records)
    .find((record) => record.source_record_id === "fixture-golden-0")!;
  expect(old.has_detail_page).toBe(false);
  await page.route("**/data/notifications/manifest.json", (route) =>
    route.fulfill({ json: golden.aged.manifest }),
  );
  await page.route(/\/data\/notifications\/fixture-.*\.json$/, (route) => {
    const asset = new URL(route.request().url()).pathname
      .split("/")
      .at(-1)!
      .slice(0, -5);
    return route.fulfill({ json: golden.aged.partitions[asset] });
  });
  await page.goto("/notifications/fixture-golden-0/");
  await page.locator("[data-legacy-record-link]").click();
  await expect(page.locator("[data-record-dialog]")).toBeVisible();
  await expect(page.locator("[data-record-dialog-title]")).toHaveText(
    "Straße Example",
  );
});

test("retired or missing bookmarks explain the publication boundary", async ({
  page,
}) => {
  await routeGolden(page);
  await page.goto("/latest/#query=fixture-retired&record=fixture-retired");
  await expect(page.locator("[data-result-count]")).toContainText(
    "not available in this publication",
  );
  await expect(page.locator("[data-record-dialog]")).not.toBeVisible();
  await expect(page.locator("[data-export-results]")).toBeDisabled();
});

for (const width of [390, 1280]) {
  test(`keyboard pagination restores focus at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const template = Object.values(golden.partitions)[0]!.records[0]!;
    const records = Array.from({ length: 121 }, (_, index) => ({
      ...template,
      source_record_id: `focus-fixture-${index}`,
      named_entity: {
        ...template.named_entity,
        source_name: `Focus Example ${index}`,
      },
    }));
    const id = "fixture-2026-001";
    const body = JSON.stringify({
      schema_version: "1.0",
      partition_id: id,
      records,
    });
    const sha256 = createHash("sha256").update(body).digest("hex");
    const metadata = {
      ...golden.manifest.partitions[0]!,
      id,
      asset: `${id}-${sha256.slice(0, 16)}`,
      sha256,
      count: records.length,
      bytes: Buffer.byteLength(body),
      query_bloom: "ff".repeat(2048),
    };
    const manifest = {
      ...golden.manifest,
      record_count: records.length,
      partition_size: 250,
      query_routing: {
        ...golden.manifest.query_routing,
        normalization_version: undefined,
      },
      partitions: [metadata],
    };
    await page.route("**/data/notifications/manifest.json", (route) =>
      route.fulfill({ json: manifest }),
    );
    await page.route(`**/data/notifications/${metadata.asset}.json`, (route) =>
      route.fulfill({ body, contentType: "application/json" }),
    );
    await page.goto("/latest/#query=Focus");
    await expect(page.locator("[data-result-count]")).toContainText(
      "121 matching source records",
    );
    const next = page
      .locator("[data-results]")
      .getByRole("link", { name: "Next", exact: true })
      .first();
    await next.focus();
    await next.press("Enter");
    await expect(page.locator("[data-result-count]")).toBeFocused();
    await expect(page.locator("[data-result-count]")).toContainText(
      "page 2 of 3",
    );
    const previous = page
      .locator("[data-results]")
      .getByRole("link", { name: "Previous", exact: true })
      .first();
    await previous.focus();
    await previous.press("Enter");
    await expect(page.locator("[data-result-count]")).toBeFocused();
    await page.goBack();
    await expect(page.locator("[data-result-count]")).toContainText(
      "page 2 of 3",
    );
    await expect(page.locator("[data-result-count]")).toBeFocused();
    await page.locator('[name="query"]').fill("Focus Example");
    await expect(page.locator('[name="query"]')).toBeFocused();
  });
}
