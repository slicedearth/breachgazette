import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("Australian landing separates aggregate records from incidents", async ({ page }) => {
  await page.goto("/australia/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Australia");
  await expect(page.getByText("not named incidents")).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
});

test("NSW register displays its rolling-window warning", async ({ page }) => {
  await page.goto("/australia/public-notifications/");
  await expect(page.getByText(/not a complete list/i)).toBeVisible();
  await expect(page.getByText(/Disappearance is not evidence of remediation/i)).toBeVisible();
});

test("source health exposes freshness without claiming factual completeness", async ({ page }) => {
  await page.goto("/source-health/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Source health");
  await expect(page.getByText(/does not establish that an official source is factually complete/i)).toBeVisible();
  const table = page.getByRole("table");
  await expect(table).toContainText("Healthy");
  await expect(table).toContainText("OAIC NDB statistics");
  await expect(table).toContainText("NSW MNDB aggregate snapshot");
  await expect(table).not.toContainText("Oaic");
  await expect(table).not.toContainText("Nsw");
});

test("OAIC allegations and orders retain distinct labels", async ({ page }) => {
  await page.goto("/australia/regulatory-actions/");
  const timeline = page.getByLabel("OAIC regulatory timeline");
  await expect(
    timeline.getByText("Civil Proceeding Allegation", { exact: true }).first(),
  ).toBeVisible();
  await expect(timeline.getByText("Civil Penalty Order", { exact: true })).toBeVisible();
  await expect(timeline.getByText(/no finding is represented/i).first()).toBeVisible();
  await page.locator('[name="legal-status"]').selectOption("civil_penalty_order");
  await expect(page.locator("[data-regulatory-event]:visible")).toHaveCount(1);
});

test("United States pages preserve source role warnings", async ({ page }) => {
  await page.goto("/united-states/washington/");
  await expect(page.getByText(/not necessarily the entity where the breach occurred/i)).toBeVisible();
  await page.goto("/united-states/california/");
  await expect(page.getByText(/does not retrieve or reproduce sample notification letters/i)).toBeVisible();
});

test("organization and candidate relationship pages explain evidence", async ({ page }) => {
  await page.goto("/organizations/org_1111111111111111/");
  await expect(page.getByText("Exact normalized source name")).toBeVisible();
  await page.goto("/relationships/");
  await expect(page.getByText("Showing relationships 1–1 of 1.")).toBeVisible();
  await expect(page.getByText("Page 1 of 1")).toBeVisible();
  await page.goto("/relationships/candidate_fixture_1/");
  await expect(page.getByText(/not a declaration/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Displayed evidence" })).toBeVisible();
});

test("keyboard navigation exposes skip link and table alternatives", async ({ page, browserName }) => {
  await page.goto("/");
  const skipLink = page.getByRole("link", { name: "Skip to content" });
  if (browserName === "webkit") {
    // Headless WebKit follows the host's full-keyboard-access preference, so
    // focus the link directly before checking its keyboard activation.
    await skipLink.focus();
  } else {
    await page.keyboard.press("Tab");
  }
  await expect(skipLink).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  await page.goto("/australia/");
  await expect(page.getByRole("table", { name: /OAIC aggregate metrics/i })).toBeVisible();
  await page.goto("/latest/");
  await expect(
    page.getByRole("navigation", { name: "Primary" }).getByRole("link", {
      name: "Notifications",
    }),
  ).toHaveAttribute("aria-current", "page");
});

test("mobile primary navigation is compact and keyboard operable", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/latest/");

  const toggle = page.getByRole("button", { name: "Menu" });
  const navigation = page.getByRole("navigation", { name: "Primary" });
  await expect(toggle).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(navigation).toBeHidden();
  const headerGeometry = await page.evaluate(() => {
    const brand = document.querySelector<HTMLElement>(".brand")?.getBoundingClientRect();
    const menu = document.querySelector<HTMLElement>(".nav-toggle")?.getBoundingClientRect();
    return {
      brandRight: brand?.right ?? 0,
      menuLeft: menu?.left ?? 0,
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    };
  });
  expect(headerGeometry.brandRight).toBeLessThanOrEqual(headerGeometry.menuLeft);
  expect(headerGeometry.scrollWidth).toBeLessThanOrEqual(headerGeometry.clientWidth);

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(navigation).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Notifications" }))
    .toHaveAttribute("aria-current", "page");

  const geometry = await navigation.evaluate((element) => {
    const links = [...element.querySelectorAll("a")];
    return {
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      linkHeights: links.map((link) => link.getBoundingClientRect().height),
      linkWidths: links.map((link) => link.getBoundingClientRect().width),
    };
  });
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
  expect(geometry.linkHeights.every((height) => height >= 44)).toBe(true);
  expect(geometry.linkWidths.every((width) => width <= geometry.clientWidth)).toBe(true);

  await page.keyboard.press("Escape");
  await expect(navigation).toBeHidden();
  await expect(toggle).toBeFocused();

  await page.setViewportSize({ width: 900, height: 900 });
  await expect(toggle).toBeHidden();
  await expect(navigation).toBeVisible();
});

test("mobile notification search keeps advanced controls compact and resettable", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/latest/");

  const advanced = page.locator("[data-advanced-filters]");
  const reset = page.getByRole("button", { name: "Clear filters" });
  const query = page.getByLabel("Organization or agency");
  await expect(advanced).not.toHaveAttribute("open");
  await expect(page.getByLabel("Breach cause")).toBeHidden();
  await expect(reset).toBeDisabled();

  await query.fill("Example");
  await expect(reset).toBeEnabled();
  await expect(page).toHaveURL(/#query=Example$/);

  await advanced.locator("summary").click();
  await page.getByLabel("Affected population").selectOption("1000_9999");
  await expect(advanced).toHaveAttribute("open");
  await expect(advanced.locator("[data-advanced-filter-count]")).toHaveText("1 active");
  await expect(page).toHaveURL(/population=1000_9999/);

  await reset.click();
  await expect(query).toHaveValue("");
  await expect(page.getByLabel("Affected population")).toHaveValue("");
  await expect(advanced).not.toHaveAttribute("open");
  await expect(reset).toBeDisabled();
  await expect(page).not.toHaveURL(/#/);
  await expect(page.locator("[data-result-count]")).toContainText("no search partitions loaded");

  await page.setViewportSize({ width: 900, height: 900 });
  await expect(advanced).toHaveAttribute("open");
  await expect(page.getByLabel("Breach cause")).toBeVisible();
});

test("desktop and mobile layouts contain overflow without fragmenting text", async ({ page }) => {
  const paths = [
    "/",
    "/latest/",
    "/sources/",
    "/source-health/",
    "/australia/public-notifications/",
    "/sources/oaic_ndb/",
  ];
  for (const width of [320, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const path of paths) {
      await page.goto(path);
      const sizes = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(sizes.scrollWidth, `${path} overflowed at ${width}px`)
        .toBeLessThanOrEqual(sizes.clientWidth);
    }
  }
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/latest/");
  const geometry = await page.evaluate(() => {
    const heading = document.querySelector("h1");
    const navigation = document.querySelector<HTMLElement>(".masthead nav");
    const wrapper = document.querySelector<HTMLElement>(".table-wrap");
    const header = document.querySelector<HTMLElement>("thead th");
    return {
      headingOverflowWrap: heading ? getComputedStyle(heading).overflowWrap : "",
      headingWordBreak: heading ? getComputedStyle(heading).wordBreak : "",
      navigationClientWidth: navigation?.clientWidth ?? 0,
      navigationScrollWidth: navigation?.scrollWidth ?? 0,
      tableClientWidth: wrapper?.clientWidth ?? 0,
      tableScrollWidth: wrapper?.scrollWidth ?? 0,
      tableHeaderWhiteSpace: header ? getComputedStyle(header).whiteSpace : "",
    };
  });
  expect(geometry.headingOverflowWrap).toBe("normal");
  expect(geometry.headingWordBreak).toBe("normal");
  expect(geometry.navigationScrollWidth).toBeLessThanOrEqual(geometry.navigationClientWidth);
  expect(geometry.tableScrollWidth).toBeGreaterThan(geometry.tableClientWidth);
  expect(geometry.tableHeaderWhiteSpace).toBe("nowrap");

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/sources/");
  const sourceHeadingGeometry = await page.locator(".source-card h2").evaluateAll(
    (headings) => headings.map((heading) => {
      const style = getComputedStyle(heading);
      return {
        fontSize: Number.parseFloat(style.fontSize),
        overflowWrap: style.overflowWrap,
        wordBreak: style.wordBreak,
      };
    }),
  );
  expect(sourceHeadingGeometry.length).toBeGreaterThan(0);
  expect(Math.max(...sourceHeadingGeometry.map((heading) => heading.fontSize)))
    .toBeLessThanOrEqual(29);
  expect(sourceHeadingGeometry.every((heading) => heading.overflowWrap === "normal"))
    .toBe(true);
  expect(sourceHeadingGeometry.every((heading) => heading.wordBreak === "normal"))
    .toBe(true);
});

test("runtime requests remain same-origin and no remote font or analytics is present", async ({ page }) => {
  const origins = new Set<string>();
  const paths: string[] = [];
  page.on("request", (request) => origins.add(new URL(request.url()).origin));
  page.on("request", (request) => paths.push(new URL(request.url()).pathname));
  await page.goto("/latest/");
  await expect(page.locator("[data-result-count]")).toContainText("published source records");
  const data = await page.evaluate(async () => {
    const manifestResponse = await fetch("/data/notifications/manifest.json");
    const manifest = await manifestResponse.json() as {
      record_count: number;
      partitions: Array<{ id: string }>;
    };
    const partitionResponse = await fetch(
      `/data/notifications/${encodeURIComponent(manifest.partitions[0]!.id)}.json`,
    );
    const partition = await partitionResponse.json() as {
      records: Array<{ has_detail_page?: boolean }>;
    };
    return { manifest, partition };
  });
  expect(data.manifest.record_count).toBeGreaterThan(0);
  expect(data.partition.records.every((record) => typeof record.has_detail_page === "boolean")).toBe(true);
  expect(await page.locator("[data-results] a").count()).toBeGreaterThan(0);
  await expect(page.locator("script:not([src])")).toHaveCount(0);
  expect([...origins]).toEqual(["http://127.0.0.1:41733"]);
  expect(paths).not.toContain("/data/notifications.json");
  const content = await page.content();
  expect(content).not.toMatch(/google-analytics|googletagmanager|fonts\.googleapis/i);
});

test("notification search defers partitions until a filter is used", async ({ page }) => {
  const paths: string[] = [];
  page.on("request", (request) => paths.push(new URL(request.url()).pathname));
  await page.goto("/latest/");
  await expect(page.locator("[data-result-count]")).toContainText("no search partitions loaded");
  expect(paths).toContain("/data/notifications/manifest.json");
  const isPartition = (path: string) =>
    path.startsWith("/data/notifications/") &&
    path.endsWith(".json") &&
    !path.endsWith("/manifest.json");
  expect(paths.some(isPartition)).toBe(false);
  await page.locator('[name="source"]').selectOption("washington");
  await expect(page.locator("[data-result-count]")).toContainText("matching source records");
  expect(paths.some(isPartition)).toBe(true);
});

test("filtered notification pagination preserves URL state and every match", async ({
  page,
}) => {
  const fixture = JSON.parse(
    await readFile(
      "../tests/fixtures/site/search-partitions/fixture-2026-001.json",
      "utf8",
    ),
  ) as {
    schema_version: string;
    partition_id: string;
    records: Array<Record<string, unknown> & {
      named_entity: Record<string, unknown>;
    }>;
  };
  const template = fixture.records.find(
    (record) => record.source_id === "washington",
  );
  expect(template).toBeDefined();
  const records = Array.from({ length: 55 }, (_, index) => ({
    ...template!,
    source_record_id: `fixture-wa-${String(index + 1).padStart(2, "0")}`,
    named_entity: {
      ...template!.named_entity,
      source_name: `Example Services Cooperative ${String(index + 1).padStart(2, "0")}`,
    },
  }));
  const partitionBody = JSON.stringify({ ...fixture, records });
  const manifest = JSON.parse(
    await readFile("../tests/fixtures/site/search-manifest.json", "utf8"),
  ) as {
    record_count: number;
    partitions: Array<{ count: number; bytes: number }>;
  };
  manifest.record_count = records.length;
  manifest.partitions[0]!.count = records.length;
  manifest.partitions[0]!.bytes = Buffer.byteLength(partitionBody);
  await page.route("**/data/notifications/manifest.json", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(manifest) }),
  );
  await page.route("**/data/notifications/fixture-2026-001.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: partitionBody,
    }),
  );

  await page.goto("/latest/");
  await page.locator('[name="source"]').selectOption("washington");
  await expect(page.locator("[data-result-count]")).toContainText(
    "55 matching source records",
  );
  await expect(page.locator("[data-result-count]")).toContainText(
    "Showing 1–50 on filtered page 1 of 2",
  );
  await expect(page.locator("[data-results] tbody tr")).toHaveCount(50);

  await page
    .getByRole("navigation", { name: "Filtered notification pages above results" })
    .getByRole("link", { name: "Next" })
    .click();
  await expect(page).toHaveURL(/#source=washington&page=2$/);
  await expect(page.locator("[data-results] tbody tr")).toHaveCount(5);
  await expect(page.locator("[data-result-count]")).toContainText(
    "Showing 51–55 on filtered page 2 of 2",
  );

  await page.reload();
  await expect(page.locator("[data-results] tbody tr")).toHaveCount(5);
  await expect(page.locator('[name="source"]')).toHaveValue("washington");
  await expect(page.locator("[data-result-count]")).toContainText(
    "Showing 51–55 on filtered page 2 of 2",
  );
});

test("complete-dataset filtering remains bounded at 10,000 records", async ({ page }) => {
  const fixture = JSON.parse(
    await readFile(
      "../tests/fixtures/site/search-partitions/fixture-2026-001.json",
      "utf8",
    ),
  ) as {
    schema_version: string;
    records: Array<Record<string, unknown> & {
      named_entity: Record<string, unknown>;
    }>;
  };
  const template = fixture.records[0]!;
  const partitionBodies = new Map<string, string>();
  const partitionMetadata = Array.from({ length: 40 }, (_, partitionIndex) => {
    const id = `scale-2026-${String(partitionIndex + 1).padStart(3, "0")}`;
    const records = Array.from({ length: 250 }, (_, recordIndex) => {
      const sequence = partitionIndex * 250 + recordIndex + 1;
      return {
        ...template,
        source_id: "scale",
        source_record_id: `scale-${String(sequence).padStart(5, "0")}`,
        jurisdiction: "Scale jurisdiction",
        regulator: "Scale regulator",
        named_entity: {
          ...template.named_entity,
          source_name: `Scale organization ${String(sequence).padStart(5, "0")}`,
        },
        has_detail_page: false,
      };
    });
    const body = JSON.stringify({
      schema_version: fixture.schema_version,
      partition_id: id,
      records,
    });
    partitionBodies.set(id, body);
    return {
      id,
      count: records.length,
      bytes: Buffer.byteLength(body),
      query_bloom: "ff",
      jurisdictions: ["Scale jurisdiction"],
      regulators: ["Scale regulator"],
      sources: ["scale"],
      years: ["2026"],
      causes: ["cyberattack"],
      information_categories: ["health_information"],
      population_bands: ["500_999"],
      roles: ["notifying_entity"],
      publication_levels: ["regulator_register_entry"],
    };
  });
  const facets = {
    jurisdictions: ["Scale jurisdiction"],
    regulators: ["Scale regulator"],
    sources: ["scale"],
    years: ["2026"],
    causes: ["cyberattack"],
    information_categories: ["health_information"],
    population_bands: ["500_999"],
    roles: ["notifying_entity"],
    publication_levels: ["regulator_register_entry"],
  };
  await page.route("**/data/notifications/manifest.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "1.0",
        generated_at: "2026-01-01T00:00:00Z",
        record_count: 10_000,
        partition_size: 250,
        partition_max_bytes: 1_000_000,
        query_routing: {
          algorithm: "normalized_trigram_bloom",
          encoding: "hex",
          bits: 8,
          hashes: 3,
          minimum_query_length: 3,
        },
        facets,
        partitions: partitionMetadata,
      }),
    }),
  );
  const requestedPartitions: string[] = [];
  await page.route(/\/data\/notifications\/scale-2026-\d{3}\.json$/, (route) => {
    const id = new URL(route.request().url()).pathname.split("/").at(-1)!.replace(".json", "");
    const body = partitionBodies.get(id);
    expect(body).toBeDefined();
    if (!body) throw new Error(`Missing generated partition ${id}`);
    requestedPartitions.push(id);
    return route.fulfill({ contentType: "application/json", body });
  });

  await page.goto("/latest/");
  const started = Date.now();
  await page.locator('[name="source"]').selectOption("scale");
  await expect(page.locator("[data-result-count]")).toContainText(
    "10,000 matching source records",
    { timeout: 10_000 },
  );
  expect(Date.now() - started).toBeLessThan(8_000);
  expect(new Set(requestedPartitions).size).toBe(40);
  await expect(page.locator("[data-results] tbody tr")).toHaveCount(50);
  await expect(page.locator("[data-result-count]")).toContainText(
    "filtered page 1 of 200",
  );
});

test("notification search preserves the complete static register when the manifest fails", async ({ page }) => {
  await page.route("**/data/notifications/manifest.json", (route) => route.abort());
  await page.goto("/latest/");
  await expect(page.locator("[data-result-count]")).toContainText("complete static register remains available");
  expect(await page.locator("[data-results] tbody tr").count()).toBeGreaterThan(0);
});

test("notification search rejects a partition above its published byte budget", async ({ page }) => {
  const manifest = JSON.parse(
    await readFile("../tests/fixtures/site/search-manifest.json", "utf8"),
  ) as { partitions: Array<{ bytes: number }> };
  manifest.partitions[0]!.bytes = 1;
  await page.route("**/data/notifications/manifest.json", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(manifest) }),
  );

  await page.goto("/latest/");
  await page.locator('[name="source"]').selectOption("washington");
  await expect(page.locator("[data-result-count]")).toContainText(
    "Search partitions could not be loaded",
  );
  await expect(page.locator("[data-results] tbody tr")).toHaveCount(3);
});

test("full notification filters preserve source fields and population bands", async ({ page }) => {
  await page.goto("/latest/");
  await page.locator('[name="source"]').selectOption("washington");
  await page.locator('[name="date"]').fill("2026-01-02");
  await page.locator('[name="cause"]').selectOption("cyberattack");
  await page.locator('[name="information"]').selectOption("health_information");
  await page.locator('[name="population"]').selectOption("500_999");
  await page.locator('[name="role"]').selectOption("notifying_entity");
  await page.locator('[name="publication"]').selectOption("regulator_register_entry");
  await expect(page.locator("[data-result-count]")).toContainText("1 matching source records");
  await expect(page.getByRole("link", { name: "Example Services Cooperative" })).toBeVisible();
});

test("search includes regulator fields and exports every filtered match", async ({ page }) => {
  await page.goto("/latest/");
  await page.locator('[name="query"]').fill("Washington Attorney General");
  await expect(page.locator("[data-result-count]")).toContainText("1 matching source records");
  const download = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export matching CSV" }).click(),
  ]).then(([item]) => item);
  expect(download.suggestedFilename()).toBe("breach-gazette-notifications.csv");
  const path = await download.path();
  expect(path).not.toBeNull();
  const csv = await readFile(path!, "utf8");
  expect(csv).toContain('"washington","fixture-wa-1"');
  expect(csv).toContain('"Washington Attorney General"');
  expect(csv.trim().split(/\r?\n/)).toHaveLength(2);
});

test("search filters can be restored from a server-private URL fragment", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto("/latest/#jurisdiction=Washington&query=Example+Services");
  await expect(page.getByLabel("Jurisdiction")).toHaveValue("Washington");
  await expect(page.getByLabel("Organization or agency")).toHaveValue("Example Services");
  await expect(page.getByText(/1 matching source records/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy search link" })).toBeEnabled();
  expect(requests.every((url) => !url.includes("#"))).toBe(true);
  await page.reload();
  await expect(page.getByLabel("Jurisdiction")).toHaveValue("Washington");
  await expect(page.getByLabel("Organization or agency")).toHaveValue("Example Services");
});

test("publication identity and source corrections are readable and reproducible", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const stamp = page.getByLabel("Current publication");
  await expect(stamp).toContainText("Verified 1 Jan 2026");
  await expect(stamp.locator("code")).toHaveText("ffffffffffff");
  await expect(stamp.getByRole("link", { name: "Review source health" })).toBeVisible();

  await page.goto("/corrections/");
  await expect(page.getByRole("heading", { name: "Observed source changes" })).toBeVisible();
  await expect(page.locator("pre")).toHaveCount(0);
  await expect(page.getByText("Source Record Corrected")).toBeVisible();
  await expect(page.getByRole("heading", {
    name: "Washington Attorney General breach notifications",
  })).toBeVisible();
  await expect(page.getByText(
    "The normalized source record changed between comparable snapshots.",
  )).toBeVisible();
  await expect(page.getByText(/does not independently establish why/i)).toBeVisible();

  const correctionsFeed = await request.get("/feeds/corrections.xml");
  expect(correctionsFeed.ok()).toBe(true);
  expect(correctionsFeed.headers()["content-type"]).toMatch(
    /^(?:application\/atom\+xml|text\/xml)/,
  );
  const correctionsText = await correctionsFeed.text();
  expect(correctionsText).toContain("Source Record Corrected");
  expect(correctionsText).toContain(
    "The normalized source record changed between comparable snapshots.",
  );
  expect(correctionsText).not.toContain("source_checksum");
});

test("feed, crawler policy, and not-found page preserve publication boundaries", async ({
  page,
  request,
}) => {
  const feed = await request.get("/feeds/notifications.xml");
  expect(feed.ok()).toBe(true);
  expect(feed.headers()["content-type"]).toMatch(
    /^(?:application\/atom\+xml|text\/xml)/,
  );
  const feedText = await feed.text();
  expect(feedText).toContain("<feed xmlns=");
  expect(feedText).toContain("Example Regional Agency");
  expect(feedText).toContain("not an independently verified incident");
  expect(feedText).not.toContain("Synthetic test fixture");

  const robots = await request.get("/robots.txt");
  expect(await robots.text()).toContain("Sitemap:");

  await page.goto("/404.html");
  await expect(page.getByRole("heading", { name: "That record page is not available." }))
    .toBeVisible();
  await expect(page.getByText(/missing page does not mean/i)).toBeVisible();
});
