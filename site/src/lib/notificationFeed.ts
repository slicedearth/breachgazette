import type { Notification } from "./types";

export const notificationFeedUpdated = (record: Notification): string =>
  record.local_last_material_change_time ?? record.local_last_observed_time;
