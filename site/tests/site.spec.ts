import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { createHash } from "node:crypto";
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
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Update status");
  await expect(page.getByText(/does not establish that an official source is factually complete/i)).toBeVisible();
  const table = page.locator('.table-wrap[aria-label="Source health table"] table');
  await expect(table).toContainText("Healthy");
  await expect(table).toContainText("OAIC NDB statistics");
  await expect(table).toContainText("NSW MNDB aggregate snapshot");
  await expect(table).not.toContainText("Oaic");
  await expect(table).not.toContainText("Nsw");
  const evidence = page.locator(".source-evidence-grid");
  await expect(evidence).toContainText("fixture-washington-revision");
  await expect(evidence).toContainText("Accepted");
  await expect(evidence).toContainText("Rejected");
  await expect(evidence).toContainText("Bounded limit");
  const history = page.locator(
    '.table-wrap[aria-label="Bounded source health history table"] table',
  );
  await expect(history).toContainText("29 Dec 2025");
  await expect(history).toContainText("Needs attention");
  await expect(history).toContainText("Washington Attorney General breach notifications");
  await expect(page.getByText(/Private checksums and diagnostic reasons are excluded/))
    .toBeVisible();
  await page.getByRole("link", {
    name: "Washington Attorney General breach notifications",
  }).last().click();
  await expect(page.getByText("fixture-washington-revision")).toBeVisible();
  await expect(page.getByText("10,000")).toBeVisible();
});

test("source coverage exposes record units and comparison boundaries", async ({ page }) => {
  await page.goto("/source-coverage/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Compare sources",
  );
  const table = page.getByRole("table", { name: "Source coverage matrix" });
  await expect(table).toContainText("Regulator Register Entry");
  await expect(table).toContainText("State Aggregate");
  await expect(table).toContainText("CNIL personal data breach notifications");
  await expect(table).toContainText("2 rows / 4 cells");
  await expect(table).toContainText("Compare only matching periods");
  await expect(table).toContainText("not a count of unique incidents");
  await expect(table).toContainText("no organization or incident inference");
  await expect(page.getByRole("heading", { name: "Four publication lanes" })).toBeVisible();
});

test("source information pages share clear local navigation", async ({ page }) => {
  const pages = [
    ["/source-coverage/", "Compare sources", "Compare sources"],
    ["/sources/", "Source policies", "Source policies"],
    ["/source-health/", "Update status", "Update status"],
  ] as const;

  for (const [path, heading, currentLink] of pages) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading);
    const navigation = page.getByRole("navigation", { name: "Source information" });
    await expect(navigation.getByRole("link", { name: "Compare sources" })).toBeVisible();
    await expect(navigation.getByRole("link", { name: "Source policies" })).toBeVisible();
    await expect(navigation.getByRole("link", { name: "Update status" })).toBeVisible();
    await expect(navigation.getByRole("link", { name: currentLink })).toHaveAttribute(
      "aria-current",
      "page",
    );
  }
});

test("France view publishes grouped CNIL counts without organization inference", async ({ page }) => {
  await page.goto("/france/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "France’s CNIL notification patterns",
  );
  await expect(page.getByText("anonymized source rows")).toBeVisible();
  await expect(page.getByText(/Rows are notifications, not unique breach incidents/i))
    .toBeVisible();
  await expect(page.getByRole("table", { name: "CNIL monthly notification rows" }))
    .toContainText("2025-12");
  await expect(
    page.getByRole("navigation", { name: "Primary" }).getByRole("link", {
      name: "Jurisdictions",
    }),
  ).toHaveAttribute("aria-current", "page");
});

test("United Kingdom view preserves unique-report and category boundaries", async ({ page }) => {
  await page.goto("/united-kingdom/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "UK ICO data security incident trends",
  );
  await expect(page.getByText(/Category totals can exceed unique reports/i)).toBeVisible();
  await expect(page.getByText("This source is not present in the current publication."))
    .toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Primary" }).getByRole("link", {
      name: "Jurisdictions",
    }),
  ).toHaveAttribute("aria-current", "page");
});

test("Netherlands view keeps annual dimensions separate", async ({ page }) => {
  await page.goto("/netherlands/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Netherlands AP data breach reports",
  );
  await expect(page.getByText(/dimensions overlap and must not be summed/i)).toBeVisible();
  const table = page.getByRole("table", {
    name: "Netherlands AP annual aggregate values",
  });
  await expect(table).toContainText("39,407");
  await expect(table).toContainText("Cyberattack");
  await expect(table).toContainText("Account takeover");
  await expect(
    page.getByRole("navigation", { name: "Primary" }).getByRole("link", {
      name: "Jurisdictions",
    }),
  ).toHaveAttribute("aria-current", "page");
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
  await page.goto("/united-states/");
  await expect(page.getByText("Reviewed but deferred:")).toBeVisible();
  await expect(page.getByRole("link", { name: "Texas" })).toHaveAttribute(
    "href",
    "/sources/texas/",
  );
  await expect(page.getByRole("link", { name: "Maine" })).toHaveAttribute(
    "href",
    "/sources/maine/",
  );
});

test("organization profiles and paginated relationships explain evidence", async ({
  page,
  request,
}) => {
  await page.goto("/organizations/org_1111111111111111/");
  await expect(page.getByText("Exact normalized source name")).toBeVisible();
  await page.goto("/relationships/");
  await expect(page.getByText("Showing relationships 1–1 of 1.")).toBeVisible();
  await expect(page.getByText("Page 1 of 1")).toBeVisible();
  await expect(page.getByText(/does not merge source provenance/i)).toBeVisible();
  const relationship = page.locator("#candidate_fixture_1");
  await expect(relationship).toBeVisible();
  await expect(
    relationship.getByRole("heading", { name: "candidate_fixture_1" }),
  ).toBeVisible();
  await expect(relationship.getByText("fixture-ca-1 and fixture-wa-1")).toBeVisible();
  await expect(
    relationship.getByRole("heading", { name: "Displayed evidence" }),
  ).toBeVisible();
  await expect(
    relationship.getByRole("heading", { name: "Limitations" }),
  ).toBeVisible();
  await expect(relationship.getByRole("link", { name: "candidate_fixture_1" }))
    .toHaveAttribute("href", "/relationships/#candidate_fixture_1");
  const redundantDetail = await request.get("/relationships/candidate_fixture_1/");
  expect(redundantDetail.status()).toBe(404);
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

test("representative desktop and mobile pages pass automated accessibility checks", async ({
  page,
}) => {
  const routes = [
    "/",
    "/latest/",
    "/jurisdictions/",
    "/france/",
    "/netherlands/",
    "/united-kingdom/",
    "/source-health/",
    "/source-coverage/",
    "/corrections/",
    "/relationships/",
  ];
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 320, height: 900 },
  ]) {
    await page.setViewportSize(viewport);
    for (const route of routes) {
      await page.goto(route);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      expect(
        results.violations,
        `${route} at ${viewport.width}px: ${results.violations
          .map((violation) => `${violation.id} (${violation.nodes.length})`)
          .join(", ")}`,
      ).toEqual([]);
    }
  }
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
  await expect(page.getByRole("button", { name: "Remove Search filter" })).toBeVisible();

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

test("desktop and mobile layouts contain content without horizontal scrollers", async ({ page }) => {
  const paths = [
    "/",
    "/latest/",
    "/sources/",
    "/jurisdictions/",
    "/australia/",
    "/australia/nsw/",
    "/australia/public-notifications/",
    "/france/",
    "/netherlands/",
    "/united-kingdom/",
    "/united-states/california/",
    "/united-states/massachusetts/",
    "/united-states/washington/",
    "/source-health/",
    "/source-coverage/",
    "/relationships/",
    "/organizations/org_1111111111111111/",
    "/sources/oaic_ndb/",
  ];
  const tablePaths = [
    "/",
    "/latest/",
    "/australia/",
    "/australia/nsw/",
    "/australia/public-notifications/",
    "/france/",
    "/netherlands/",
    "/united-kingdom/",
    "/united-states/california/",
    "/united-states/massachusetts/",
    "/united-states/washington/",
    "/source-health/",
    "/source-coverage/",
    "/organizations/org_1111111111111111/",
  ];
  for (const width of [320, 390, 768, 1440]) {
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
    const unlabeledCells = [
      ...document.querySelectorAll<HTMLElement>(".table-wrap tbody tr > th, .table-wrap tbody tr > td"),
    ].filter((cell) => !cell.dataset.label).length;
    return {
      headingOverflowWrap: heading ? getComputedStyle(heading).overflowWrap : "",
      headingWordBreak: heading ? getComputedStyle(heading).wordBreak : "",
      navigationClientWidth: navigation?.clientWidth ?? 0,
      navigationScrollWidth: navigation?.scrollWidth ?? 0,
      tableClientWidth: wrapper?.clientWidth ?? 0,
      tableScrollWidth: wrapper?.scrollWidth ?? 0,
      tableHeaderWhiteSpace: header ? getComputedStyle(header).whiteSpace : "",
      unlabeledCells,
    };
  });
  expect(geometry.headingOverflowWrap).toBe("normal");
  expect(geometry.headingWordBreak).toBe("normal");
  expect(geometry.navigationScrollWidth).toBeLessThanOrEqual(geometry.navigationClientWidth);
  expect(geometry.tableScrollWidth).toBeLessThanOrEqual(geometry.tableClientWidth);
  expect(geometry.tableHeaderWhiteSpace).toBe("nowrap");
  expect(geometry.unlabeledCells).toBe(0);

  for (const width of [320, 390, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    for (const path of tablePaths) {
      await page.goto(path);
      const tableRegions = await page.locator(".table-wrap").evaluateAll((wrappers) =>
        wrappers.map((wrapper) => ({
          clientWidth: wrapper.clientWidth,
          scrollWidth: wrapper.scrollWidth,
          unlabeledCells: [
            ...wrapper.querySelectorAll<HTMLElement>("tbody tr > th, tbody tr > td"),
          ].filter((cell) => !cell.dataset.label).length,
          cellStyles: [
            ...wrapper.querySelectorAll<HTMLElement>("tbody tr > th, tbody tr > td"),
          ].map((cell) => {
            const style = getComputedStyle(cell);
            return {
              cellWidth: cell.getBoundingClientRect().width,
              gridColumnCount: style.gridTemplateColumns.trim().split(/\s+/).length,
              overflowWrap: style.overflowWrap,
              rowWidth: cell.parentElement?.getBoundingClientRect().width ?? 0,
              wordBreak: style.wordBreak,
              hyphens: style.hyphens,
            };
          }),
        })),
      );
      expect(tableRegions.length, `${path} did not render a table`).toBeGreaterThan(0);
      expect(
        tableRegions.every((region) => region.scrollWidth <= region.clientWidth),
        `${path} contained a horizontal table scroller at ${width}px`,
      ).toBe(true);
      expect(
        tableRegions.every((region) => region.unlabeledCells === 0),
        `${path} contained an unlabeled mobile table cell`,
      ).toBe(true);
      expect(
        tableRegions.every((region) =>
          region.cellStyles.every((style) =>
            Math.abs(style.rowWidth - style.cellWidth) <= 2)),
        `${path} retained a desktop column width on mobile at ${width}px`,
      ).toBe(true);
      expect(
        tableRegions.every((region) =>
          region.cellStyles.every((style) => (
            style.overflowWrap === "break-word"
            && style.wordBreak === "normal"
            && style.hyphens === "none"
          ))),
        `${path} allowed mobile table values to split ordinary words at ${width}px`,
      ).toBe(true);
      expect(
        tableRegions.every((region) =>
          region.cellStyles.every((style) =>
            width <= 480 ? style.gridColumnCount === 1 : style.gridColumnCount === 2)),
        `${path} used a cramped mobile table layout at ${width}px`,
      ).toBe(true);
    }
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/source-coverage/");
  const coverageTableGeometry = await page.locator(".table-wrap").evaluate((wrapper) => ({
    clientWidth: wrapper.clientWidth,
    scrollWidth: wrapper.scrollWidth,
  }));
  expect(coverageTableGeometry.scrollWidth).toBeLessThanOrEqual(
    coverageTableGeometry.clientWidth,
  );

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
      partitions: Array<{ asset: string }>;
    };
    const partitionResponse = await fetch(
      `/data/notifications/${encodeURIComponent(manifest.partitions[0]!.asset)}.json`,
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
  const contentSecurityPolicy = await page
    .locator('meta[http-equiv="Content-Security-Policy"]')
    .getAttribute("content");
  expect(contentSecurityPolicy).toContain("style-src 'self'");
  expect(contentSecurityPolicy).toContain("form-action 'none'");
  expect(contentSecurityPolicy).not.toContain("'unsafe-inline'");
  expect(contentSecurityPolicy).not.toContain("upgrade-insecure-requests");
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
      "../tests/fixtures/site/search-partitions/fixture-2026-001-9b649946303bccbf.json",
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
    partitions: Array<{ asset: string; count: number; bytes: number; sha256: string }>;
  };
  manifest.record_count = records.length;
  manifest.partitions[0]!.count = records.length;
  manifest.partitions[0]!.bytes = Buffer.byteLength(partitionBody);
  manifest.partitions[0]!.sha256 = createHash("sha256").update(partitionBody).digest("hex");
  manifest.partitions[0]!.asset =
    `${manifest.partitions[0]!.asset.slice(0, -"9b649946303bccbf".length)}` +
    manifest.partitions[0]!.sha256.slice(0, 16);
  await page.route("**/data/notifications/manifest.json", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(manifest) }),
  );
  await page.route(`**/data/notifications/${manifest.partitions[0]!.asset}.json`, (route) =>
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
      "../tests/fixtures/site/search-partitions/fixture-2026-001-9b649946303bccbf.json",
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
    const sha256 = createHash("sha256").update(body).digest("hex");
    const asset = `${id}-${sha256.slice(0, 16)}`;
    partitionBodies.set(asset, body);
    return {
      id,
      asset,
      count: records.length,
      bytes: Buffer.byteLength(body),
      sha256,
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
  const facetCounts = {
    jurisdictions: { "Scale jurisdiction": 10_000 },
    regulators: { "Scale regulator": 10_000 },
    sources: { scale: 10_000 },
    years: { "2026": 10_000 },
    causes: { cyberattack: 10_000 },
    information_categories: { health_information: 10_000 },
    population_bands: { "500_999": 10_000 },
    roles: { notifying_entity: 10_000 },
    publication_levels: { regulator_register_entry: 10_000 },
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
        facet_counts: facetCounts,
        partitions: partitionMetadata,
      }),
    }),
  );
  const requestedPartitions: string[] = [];
  await page.route(/\/data\/notifications\/scale-2026-\d{3}-[0-9a-f]{16}\.json$/, (route) => {
    const asset = new URL(route.request().url()).pathname.split("/").at(-1)!.replace(".json", "");
    const body = partitionBodies.get(asset);
    expect(body).toBeDefined();
    if (!body) throw new Error(`Missing generated partition ${asset}`);
    requestedPartitions.push(asset);
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
  const topPagination = page.getByRole("navigation", {
    name: "Filtered notification pages above results",
  });
  const desktopPages = topPagination.locator(".pagination__pages--desktop");
  await expect(desktopPages).toBeVisible();
  await expect(
    desktopPages.getByRole("link", { name: "Go to filtered notification page 6" }),
  ).toBeVisible();
  await expect(
    desktopPages.getByRole("link", { name: "Go to filtered notification page 200" }),
  ).toBeVisible();
  await page.getByLabel("Sort results").selectOption("organization");
  await expect(page.locator("[data-results] tbody tr").first()).toContainText(
    "Scale organization 00001",
  );

  await page.setViewportSize({ width: 320, height: 900 });
  const mobilePages = topPagination.locator(".pagination__pages--mobile");
  await expect(desktopPages).toBeHidden();
  await expect(mobilePages).toBeVisible();
  await expect(topPagination.locator(".pagination__status")).toHaveText("Page 1 of 200");
  for (const pageNumber of [2, 3, 4, 200]) {
    await expect(
      mobilePages.getByRole("link", {
        name: `Go to filtered notification page ${pageNumber}`,
        exact: true,
      }),
    ).toBeVisible();
  }
  const paginationWidths = await topPagination.evaluate((navigation) => ({
    clientWidth: navigation.clientWidth,
    scrollWidth: navigation.scrollWidth,
  }));
  expect(paginationWidths.scrollWidth).toBeLessThanOrEqual(paginationWidths.clientWidth);

  await mobilePages.getByRole("link", {
    name: "Go to filtered notification page 4",
    exact: true,
  }).click();
  await expect(page).toHaveURL(/#source=scale&sort=organization&page=4$/);
  await expect(topPagination.locator(".pagination__status")).toHaveText("Page 4 of 200");
  for (const pageNumber of [1, 3, 5, 200]) {
    await expect(
      mobilePages.getByRole("link", {
        name: `Go to filtered notification page ${pageNumber}`,
        exact: true,
      }),
    ).toBeVisible();
  }
  const boundedRecordLink = page.locator("[data-results] tbody th a").first();
  await expect(boundedRecordLink).toHaveAttribute(
    "href",
    /\/latest\/#query=scale-\d{5}&record=scale-\d{5}$/,
  );
  await boundedRecordLink.click();
  const boundedRecordDialog = page.getByRole("dialog", {
    name: /Scale organization/,
  });
  await expect(boundedRecordDialog).toBeVisible();
  await expect(
    boundedRecordDialog.getByRole("link", { name: "Open this record link" }),
  ).toHaveAttribute("href", /\/latest\/#query=scale-\d{5}&record=scale-\d{5}$/);
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

test("notification search rejects same-size partition tampering", async ({ page }) => {
  const fixture = JSON.parse(
    await readFile(
      "../tests/fixtures/site/search-partitions/fixture-2026-001-9b649946303bccbf.json",
      "utf8",
    ),
  ) as Record<string, unknown>;
  const body = JSON.stringify(fixture).replace("Example", "Tamperx");
  await page.route("**/data/notifications/fixture-2026-001-9b649946303bccbf.json", (route) =>
    route.fulfill({ contentType: "application/json", body }),
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
  await expect(
    page.getByLabel("Jurisdiction").locator('option[value="Washington"]'),
  ).toHaveText("Washington (1)");
  await page.locator('[name="source"]').selectOption("washington");
  await page.locator('[name="date_from"]').fill("2026-01-03");
  await page.locator('[name="date_to"]').fill("2026-01-02");
  await expect(page.locator("[data-result-count]")).toContainText(
    "Source date from must be on or before source date to",
  );
  await page.locator('[name="date_from"]').fill("2026-01-02");
  await page.locator('[name="cause"]').selectOption("cyberattack");
  await page.locator('[name="information"]').selectOption("health_information");
  await page.locator('[name="population"]').selectOption("500_999");
  await page.locator('[name="role"]').selectOption("notifying_entity");
  await page.locator('[name="publication"]').selectOption("regulator_register_entry");
  await expect(page.locator("[data-result-count]")).toContainText("1 matching source records");
  const filteredFacets = page.locator("[data-filtered-facets]");
  await expect(filteredFacets).toContainText("Washington (1)");
  await expect(filteredFacets).toContainText("Regulator Register Entry (1)");
  await expect(page.getByRole("button", { name: "Remove Date from filter" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove Date to filter" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Example Services Cooperative" })).toBeVisible();
  await page.getByRole("button", { name: "View record details" }).click();
  const dialog = page.getByRole("dialog", { name: "Example Services Cooperative" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("fixture-wa-1");
  await expect(dialog).toContainText("Washington Attorney General");
  await expect(dialog.getByRole("link", { name: /Open official source/ })).toHaveAttribute(
    "href",
    "https://data.wa.gov/Consumer-Protection/Data-Breach-Notifications-Affecting-Washington-Resi/sb4j-ca4h",
  );
  await dialog.getByRole("button", { name: "Close" }).click();
  await expect(dialog).toBeHidden();
});

test("search includes regulator fields and exports every filtered match", async ({ page }) => {
  await page.goto("/latest/");
  await page.locator('[name="query"]').fill("Example Washington");
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
  await expect(page.locator('select[name="jurisdiction"]')).toHaveValue("Washington");
  await expect(page.getByLabel("Organization or agency")).toHaveValue("Example Services");
  await expect(page.getByText(/1 matching source records/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy search link" })).toBeEnabled();
  expect(requests.every((url) => !url.includes("#"))).toBe(true);
  await page.reload();
  await expect(page.locator('select[name="jurisdiction"]')).toHaveValue("Washington");
  await expect(page.getByLabel("Organization or agency")).toHaveValue("Example Services");
});

test("publication identity and source corrections are readable and reproducible", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const stamp = page.getByLabel("Current publication");
  await expect(stamp).toContainText("Verified 1 Jan 2026");
  await expect(stamp.locator("code").first()).toHaveText("ffffffffffff");
  await expect(stamp.locator("code").nth(1)).toHaveText("000000000000");
  await expect(stamp.getByRole("link", { name: "Review update status" })).toBeVisible();
  await expect(page.getByRole("heading", {
    name: "What changed in the published source records",
  })).toBeVisible();
  await expect(page.getByRole("heading", { name: "First observed" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Corrected" })).toBeVisible();
  await expect(page.getByRole("heading", {
    name: "Absent from a complete snapshot",
  })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sources recovered" })).toBeVisible();

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
  await expect(page.getByRole("link", { name: "fixture-wa-1" })).toHaveAttribute(
    "href",
    "/notifications/fixture-wa-1/",
  );
  await expect(page.getByText(/does not independently establish why/i)).toBeVisible();
  await expect(page.getByText(/Showing the 1 most recently observed change of 1 retained event/)).toBeVisible();
  await expect(page.getByText(/bounded to 250 events/)).toBeVisible();

  await page.goto("/notifications/fixture-wa-1/");
  await expect(page.getByRole("heading", {
    name: "Recent observed record history",
  })).toBeVisible();
  await expect(page.getByRole("link", { name: "Source Record Corrected" }))
    .toHaveAttribute(
      "href",
      `/corrections/#event-${"c".repeat(64)}`,
    );

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

  const identityResponse = await request.get("/data/publication.json");
  expect(identityResponse.ok()).toBe(true);
  expect(identityResponse.headers()["content-type"]).toContain("application/json");
  expect(await identityResponse.json()).toMatchObject({
    source_revision: "0000000000000000000000000000000000000000",
    publication_checksum: "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    publication_checksum_algorithm: "sha256_canonical_json_v1",
    publication_checksum_scope: "publication_summary_and_search_partition_digests",
    record_counts: { notifications: 3, corrections: 1 },
    published_corrections: 1,
    max_public_corrections: 250,
    update_digest: {
      event_count: 3,
      counts: {
        records_first_observed: 1,
        records_corrected: 1,
        records_absent_from_complete_snapshot: 1,
        sources_recovered: 1,
      },
    },
  });
  await expect(page.getByRole("link", { name: "Publication identity" })).toHaveAttribute(
    "href",
    "/data/publication.json",
  );
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

  const security = await request.get("/.well-known/security.txt");
  expect(security.ok()).toBe(true);
  expect(security.headers()["content-type"]).toContain("text/plain");
  const securityText = await security.text();
  expect(securityText).toContain("Contact: https://");
  expect(securityText).toContain("Expires: 2027-07-24T00:00:00Z");
  expect(securityText).toContain("Preferred-Languages: en");
  expect(securityText).toContain(
    "Canonical: https://breachgazette.invalid/.well-known/security.txt",
  );
  const securityFallback = await request.get("/security.txt");
  expect(securityFallback.ok()).toBe(true);
  expect(securityFallback.headers()["content-type"]).toContain("text/plain");
  expect(await securityFallback.text()).toBe(securityText);

  await page.goto("/404.html");
  await expect(page.getByRole("heading", { name: "That record page is not available." }))
    .toBeVisible();
  await expect(page.getByText(/missing page does not mean/i)).toBeVisible();
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
    "content",
    "noindex,follow",
  );
});
