import { expect, test } from "@playwright/test";

const origin = "http://127.0.0.1:41735";

for (const width of [320, 1440]) {
  test(`static multi-page jump, direct entry, reload and back navigation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${origin}/latest/pages/2/`);
    const top = page.getByRole("navigation", { name: "Notification pages above results", exact: true });
    await expect(top).toContainText("Page 2 of 3");
    await expect(page.locator(".notification-table tbody tr")).toHaveCount(50);
    const jump = top.getByLabel("Jump to page");
    await jump.fill("4");
    await jump.press("Enter");
    await expect(page).toHaveURL(/\/latest\/pages\/2\/$/);
    await jump.fill("3");
    await top.getByRole("button", { name: "Go", exact: true }).click();
    await expect(page).toHaveURL(/\/latest\/pages\/3\/#notification-results$/);
    await expect(page.locator(".notification-table tbody tr")).toHaveCount(20);
    await page.reload();
    await expect(top).toContainText("Page 3 of 3");
    await expect(page.locator(".notification-table tbody tr")).toHaveCount(20);
    await page.goBack();
    await expect(page).toHaveURL(/\/latest\/pages\/2\/$/);
    await expect(top).toContainText("Page 2 of 3");
    await jump.fill("1");
    await jump.press("Enter");
    await expect(page).toHaveURL(/\/latest\/#notification-results$/);
    await expect(page.locator(".notification-table tbody tr")).toHaveCount(50);
    await expect(page.locator("[data-result-count]")).toContainText("120 published source records");
  });
}

test("no-JavaScript static navigation reaches every record across three pages", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 320, height: 900 } });
  const page = await context.newPage();
  try {
    await page.goto(`${origin}/latest/`);
    const top = page.getByRole("navigation", { name: "Notification pages above results", exact: true });
    const names = new Set<string>();
    for (const number of [1, 2, 3]) {
      await expect(top).toContainText(`Page ${number} of 3`);
      await expect(top.getByLabel("Jump to page")).toHaveCount(0);
      const rows = page.locator(".notification-table tbody tr");
      await expect(rows).toHaveCount(number === 3 ? 20 : 50);
      for (const text of await rows.allTextContents()) names.add(text);
      if (number < 3) await top.getByRole("link", { name: "Next" }).click();
    }
    expect(names.size).toBe(120);
    await page.reload();
    await expect(top).toContainText("Page 3 of 3");
    await top.getByRole("link", { name: "Previous" }).click();
    await expect(top).toContainText("Page 2 of 3");
  } finally { await context.close(); }
});

test("mobile regulator hash restoration opens advanced controls and survives back and reload", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto(`${origin}/latest/#regulator=Washington+Attorney+General`);
  const advanced = page.locator("[data-advanced-filters]");
  const regulator = page.getByRole("combobox", { name: "Regulator", exact: true });
  await expect(advanced).toHaveAttribute("open");
  await expect(regulator).toBeVisible();
  await expect(regulator).toHaveValue("Washington Attorney General");
  await expect(page.locator("[data-result-count]")).toContainText("40 matching source records");
  await page.evaluate(() => { window.location.hash = "regulator=IPC+NSW"; });
  await expect(regulator).toHaveValue("IPC NSW");
  await page.goBack();
  await expect(regulator).toHaveValue("Washington Attorney General");
  await expect(regulator).toBeVisible();
  await page.reload();
  await expect(regulator).toHaveValue("Washington Attorney General");
  await expect(advanced).toHaveAttribute("open");
  await expect(page.locator("[data-result-count]")).toContainText("40 matching source records");
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(advanced).not.toHaveAttribute("open");
});

for (const width of [320, 390, 768, 1440]) {
  test(`large fixture counters fit their cells without clipping or overlap at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(origin);
    const index = page.locator(".edition-index");
    await expect(index.locator("dd")).toHaveText(["120", "100,000", "125,000", "999,999"]);
    await index.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`large-counters-${width}.png`) });
    const dimensions = await index.locator("dd").evaluateAll((elements) => elements.map((element) => {
      const range = document.createRange(); range.selectNodeContents(element);
      const text = range.getBoundingClientRect();
      const cell = element.parentElement!.getBoundingClientRect();
      const label = element.parentElement!.querySelector("dt")!.getBoundingClientRect();
      return { text: element.textContent, left: text.left, right: text.right, cellLeft: cell.left, cellRight: cell.right,
        top: text.top, labelBottom: label.bottom, width: element.clientWidth, scroll: element.scrollWidth };
    }));
    for (const size of dimensions) {
      expect(size.right, JSON.stringify(size)).toBeLessThanOrEqual(size.cellRight + 1);
      expect(size.left, JSON.stringify(size)).toBeGreaterThanOrEqual(size.cellLeft - 1);
      expect(size.top, JSON.stringify(size)).toBeGreaterThanOrEqual(size.labelBottom);
      expect(size.scroll, JSON.stringify(size)).toBeLessThanOrEqual(size.width + 1);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
