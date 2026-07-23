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
  await expect(page.getByRole("table")).toContainText("Healthy");
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
});

test("320 pixel layout has no document-level horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  for (const path of ["/", "/latest/", "/source-health/", "/australia/public-notifications/", "/sources/oaic_ndb/"]) {
    await page.goto(path);
    const sizes = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(sizes.scrollWidth, `page overflowed at ${path}`).toBeLessThanOrEqual(sizes.clientWidth);
  }
});

test("runtime requests remain same-origin and no remote font or analytics is present", async ({ page }) => {
  const origins = new Set<string>();
  const paths: string[] = [];
  page.on("request", (request) => origins.add(new URL(request.url()).origin));
  page.on("request", (request) => paths.push(new URL(request.url()).pathname));
  await page.goto("/latest/");
  await expect(page.locator("[data-result-count]")).toContainText("matching source records");
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

test("notification search preserves static records when the manifest fails", async ({ page }) => {
  await page.route("**/data/notifications/manifest.json", (route) => route.abort());
  await page.goto("/latest/");
  await expect(page.locator("[data-result-count]")).toContainText("latest static records remain available");
  expect(await page.locator("[data-results] tbody tr").count()).toBeGreaterThan(0);
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
