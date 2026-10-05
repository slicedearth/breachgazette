import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { notificationFeedUpdated } from "../src/lib/notificationFeed";
import type { Notification } from "../src/lib/types";

test("notification feed timestamps follow material changes with an explicit legacy fallback", async ({ request }) => {
  const [fixture] = JSON.parse(
    await readFile("../tests/fixtures/site/notifications.json", "utf8"),
  ) as Notification[];
  const original = {
    ...fixture!,
    local_last_observed_time: "2026-01-20T10:00:00+00:00",
    local_last_material_change_time: "2026-01-15T10:00:00+00:00",
  };
  const observedAgain = {
    ...original,
    local_last_observed_time: "2026-01-27T10:00:00+00:00",
  };
  expect(notificationFeedUpdated(observedAgain)).toBe(notificationFeedUpdated(original));
  const corrected = {
    ...observedAgain,
    local_last_material_change_time: "2026-01-27T10:00:00+00:00",
  };
  expect(notificationFeedUpdated(corrected)).not.toBe(notificationFeedUpdated(original));
  expect(notificationFeedUpdated({ ...original, local_last_material_change_time: null }))
    .toBe(original.local_last_observed_time);
  const { local_last_material_change_time: _unused, ...legacy } = original;
  expect(notificationFeedUpdated(legacy)).toBe(original.local_last_observed_time);

  const response = await request.get("/feeds/notifications.xml");
  expect(response.ok()).toBe(true);
  const xml = await response.text();
  for (const record of JSON.parse(
    await readFile("../tests/fixtures/site/notifications.json", "utf8"),
  ) as Notification[]) {
    expect(xml).toContain(`<updated>${notificationFeedUpdated(record)}</updated>`);
  }
  expect(xml).not.toContain("local_last_material_change_time");
});
