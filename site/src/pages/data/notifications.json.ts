import type { APIRoute } from "astro";
import { getNotifications, getPublication } from "../../lib/data";

export const prerender = true;

export const GET: APIRoute = () => {
  const publication = getPublication();
  const details = publication.detail_notifications.length
    ? publication.detail_notifications
    : publication.latest_notifications;
  const detailIds = new Set(details.map((record) => record.source_record_id));
  const notifications = getNotifications().map((record) => ({
    ...record,
    has_detail_page: detailIds.has(record.source_record_id),
  }));
  return new Response(JSON.stringify(notifications), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
      "X-Content-Type-Options": "nosniff",
    },
  });
};
