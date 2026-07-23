import { readFileSync } from "node:fs";
import { isAbsolute, join, resolve } from "node:path";
import type { Notification, Publication } from "./types";

function dataDirectory(): string {
  const configured = process.env.BREACHGAZETTE_SITE_DATA_DIR;
  if (!configured) {
    throw new Error("BREACHGAZETTE_SITE_DATA_DIR is required");
  }
  return isAbsolute(configured) ? configured : resolve(process.cwd(), configured);
}

function readJson<T>(name: string): T {
  const path = join(dataDirectory(), name);
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

export function getPublication(): Publication {
  const publication = readJson<Publication>("publication.json");
  const datasetClass = publication.manifest?.dataset_class;
  const testBuild = process.env.BREACHGAZETTE_TEST_BUILD === "1";
  if (datasetClass !== "real_source_data" && !(testBuild && datasetClass === "test_fixture")) {
    throw new Error("Production site builds require real_source_data");
  }
  if (!publication.quality?.passed) {
    throw new Error("Publication quality report did not pass");
  }
  return publication;
}

export function getNotifications(): Notification[] {
  const notifications = readJson<Notification[]>("notifications.json");
  if (!Array.isArray(notifications)) {
    throw new Error("notifications.json is not an array");
  }
  return notifications;
}
