import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("global record views are reachable from navigation and source policies", async ({ page }) => {
  await page.goto("/latest/");
  const primary = page.getByRole("navigation", { name: "Primary", exact: true });
  await primary.getByRole("link", { name: "Regulatory actions" }).click();
  await expect(page.locator("[data-regulatory-event]")).toHaveCount(4);
  await primary.getByRole("link", { name: "Aggregate metrics" }).click();
  await expect(page.locator(".source-metric-index")).toContainText("Ireland");
  await expect(page.locator(".source-metric-index")).toContainText("Netherlands");
  await page.goto("/sources/france_cnil_regulatory/");
  await page.getByRole("link", { name: "Browse this source’s records" }).click();
  await expect(page.locator("[data-regulatory-event]:visible")).toHaveCount(1);
  await expect(page.locator("[data-regulatory-event]:visible")).toContainText("Example Data Processor");
  await page.goto("/sources/ireland_dpc/");
  await page.getByRole("link", { name: "Browse this source’s records" }).click();
  await expect(page.getByRole("table", { name: "Published aggregate metrics" })).toContainText("321");
});

test("country and homepage links do not send global totals to an Australian subset", async ({ page, request }) => {
  await page.goto("/");
  const index = page.getByRole("complementary", { name: "Four kinds of record." });
  await expect(index.getByRole("link", { name: "Aggregate metrics" })).toHaveAttribute("href", "/aggregates/");
  await expect(index.getByRole("link", { name: "Regulatory actions" })).toHaveAttribute("href", "/regulatory-actions/");
  for (const path of ["/australia/", "/france/", "/united-kingdom/", "/ireland/", "/aggregates/"]) {
    await page.goto(path);
    const links = await page.locator(".record-links a, .source-metric-index a").evaluateAll((nodes) => nodes.map((node) => (node as HTMLAnchorElement).href));
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) expect((await request.get(link)).ok(), link).toBe(true);
  }
});

test("regulatory filters distinguish administrative fines, allegations and empty results", async ({ page }) => {
  await page.goto("/regulatory-actions/");
  await page.getByLabel("Legal status").selectOption("administrative_fine");
  await expect(page.locator("[data-regulatory-event]:visible")).toHaveCount(2);
  await expect(page.locator("[data-regulatory-event]:visible").first()).toContainText("not a court judgment");
  await page.getByRole("combobox", { name: "Source", exact: true }).selectOption("france_cnil_regulatory");
  await expect(page.locator("[data-regulatory-count]")).toHaveText("1 source-backed event.");
  await page.reload();
  await expect(page.locator("[data-regulatory-event]:visible")).toHaveCount(1);
  await page.getByLabel("Legal status").selectOption("civil_proceeding_allegation");
  await expect(page.locator("[data-regulatory-empty]")).toBeVisible();
  await expect(page.locator("[data-regulatory-count]")).toHaveText("0 source-backed events.");
  await page.goto("/australia/regulatory-actions/");
  await expect(page.locator("[data-regulatory-event]")).toHaveCount(2);
  await expect(page.locator("[data-regulatory-timeline]")).not.toContainText("Example Data Processor");
  await page.goto("/matters/fixture-fr-fine/");
  await expect(page.getByText(/does not establish payment or finality on appeal/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Attribution and reuse" })).toBeVisible();
});

test("record pages remain readable without JavaScript", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:41733/regulatory-actions/");
  await expect(page.locator("[data-regulatory-event]:visible")).toHaveCount(4);
  await expect(page.locator("[data-regulatory-filters]")).toBeHidden();
  await page.goto("http://127.0.0.1:41733/aggregates/france_cnil_annual/");
  await expect(page.getByRole("table")).toContainText("654");
  await expect(page.getByText(/11,635/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Publication trail" })).toBeVisible();
  await expect(page.locator('time[datetime="2026-01-15T00:00:00Z"]')).toHaveText("15 Jan 2026");
  await page.goto("http://127.0.0.1:41733/aggregates/ireland_dpc/");
  await expect(page.getByText(/Retrieval date not provided/)).toBeVisible();
  await context.close();
});

for (const width of [320, 390, 768, 1440]) {
  test(`timeline rows and metric pages fit at ${width}px`, async ({ page }, testInfo) => {
    test.slow();
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/regulatory-actions/", "/australia/regulatory-actions/", "/aggregates/", "/aggregates/france_cnil_annual/", "/ireland/"]) {
      await page.goto(path);
      const geometry = await page.evaluate(() => ({
        width: document.documentElement.clientWidth,
        scroll: document.documentElement.scrollWidth,
        rows: [...document.querySelectorAll<HTMLElement>("[data-regulatory-event]")].map((row) => ({
          left: row.getBoundingClientRect().left, right: row.getBoundingClientRect().right,
          top: row.getBoundingClientRect().top, bottom: row.getBoundingClientRect().bottom,
          marker: getComputedStyle(row.parentElement!).listStyleType,
        })),
      }));
      expect(geometry.scroll, path).toBeLessThanOrEqual(geometry.width);
      for (const [index, row] of geometry.rows.entries()) {
        expect(row.left).toBeGreaterThanOrEqual(0);
        expect(row.right).toBeLessThanOrEqual(width);
        expect(row.marker).toBe("none");
        // Adjacent layout edges can differ by a fraction of a device pixel.
        if (index > 0) expect(row.top + 0.1).toBeGreaterThanOrEqual(geometry.rows[index - 1]!.bottom);
      }
      if ([320, 1440].includes(width)) {
        const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
        expect(result.violations, path).toEqual([]);
      }
      if (testInfo.project.name === "chromium" && [390, 1440].includes(width)
        && ["/regulatory-actions/", "/aggregates/"].includes(path)) {
        await page.screenshot({ path: testInfo.outputPath(`${path.replaceAll("/", "")}-${width}.png`), fullPage: true });
      }
    }
  });
}

test("aggregate pagination exposes all cells without JavaScript or silent truncation", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 320, height: 900 } });
  const page = await context.newPage();
  const seen = new Set<string>();
  for (let number = 1; number <= 4; number += 1) {
    await page.goto(`http://127.0.0.1:41735/aggregates/oaic_ndb/${number === 1 ? "" : `${number}/`}`);
    const rows = page.getByRole("table", { name: "Published aggregate metrics" }).locator("tbody tr");
    await expect(rows).toHaveCount(number === 4 ? 5 : 100);
    for (const name of await rows.locator("th").allTextContents()) seen.add(name);
    const nav = page.getByRole("navigation", { name: "Aggregate metric pages" });
    await expect(nav).toBeVisible();
    await expect(nav).toContainText(`Page ${number} of 4`);
    expect(await nav.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  }
  expect(seen.size).toBe(305);
  await page.goto("http://127.0.0.1:41735/australia/");
  await expect(page.getByText(/305 source cells/)).toBeVisible();
  await page.getByRole("link", { name: "Browse all national metrics by page" }).click();
  await expect(page.getByRole("table", { name: "Published aggregate metrics" }).locator("tbody tr")).toHaveCount(100);
  await expect(page.getByRole("navigation", { name: "Aggregate metric pages" })).toContainText("Page 1 of 4");
  await context.close();
});
