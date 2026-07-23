import { expect, test } from "@playwright/test";

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
  await page.goto("/relationships/candidate_fixture_1/");
  await expect(page.getByText(/not a declaration/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Displayed evidence" })).toBeVisible();
});

test("keyboard navigation exposes skip link and table alternatives", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.goto("/australia/");
  await expect(page.getByRole("table", { name: /OAIC aggregate metrics/i })).toBeVisible();
});

test("320 pixel layout has no document-level horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  for (const path of ["/", "/latest/", "/australia/public-notifications/", "/sources/oaic_ndb/"]) {
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
  page.on("request", (request) => origins.add(new URL(request.url()).origin));
  await page.goto("/latest/");
  await expect(page.locator("[data-result-count]")).toContainText("matching source records");
  const data = await page.evaluate(async () => {
    const response = await fetch("/data/notifications.json");
    return await response.json() as Array<{ has_detail_page?: boolean }>;
  });
  expect(data.every((record) => typeof record.has_detail_page === "boolean")).toBe(true);
  expect(await page.locator("[data-results] a").count()).toBeGreaterThan(0);
  await expect(page.locator("script:not([src])")).toHaveCount(0);
  expect([...origins]).toEqual(["http://127.0.0.1:41733"]);
  const content = await page.content();
  expect(content).not.toMatch(/google-analytics|googletagmanager|fonts\.googleapis/i);
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
