import type { APIRoute } from "astro";
import { getAllNotifications, getPublication } from "../../lib/data";
import type { Notification } from "../../lib/types";

const xml = (value: string) =>
  value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&apos;");

const sourceDate = (record: Notification) =>
  record.dates
    .map((item) => item.normalized_date)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);

export const GET: APIRoute = ({ site }) => {
  if (!site) throw new Error("A canonical site URL is required for the notification feed");
  const publication = getPublication();
  const feedUrl = new URL(
    `${import.meta.env.BASE_URL}feeds/notifications.xml`,
    site,
  ).toString();
  const homeUrl = new URL(import.meta.env.BASE_URL, site).toString();
  const entries = getAllNotifications().slice(0, 50).map((record) => {
    const detailUrl = record.has_detail_page
      ? new URL(
          `${import.meta.env.BASE_URL}notifications/${encodeURIComponent(record.source_record_id)}/`,
          site,
        ).toString()
      : record.source_url;
    const observed = sourceDate(record) ?? record.local_last_observed_time.slice(0, 10);
    const title = `${record.named_entity.source_name} — ${record.jurisdiction} notification`;
    const summary = [
      `Source role: ${record.named_entity.role}.`,
      `Regulator: ${record.regulator}.`,
      `Source date: ${observed}.`,
      "This entry represents an official source record, not an independently verified incident.",
    ].join(" ");
    return [
      "<entry>",
      `<id>${xml(`urn:breachgazette:${record.source_id}:${record.source_record_id}`)}</id>`,
      `<title>${xml(title)}</title>`,
      `<link href="${xml(detailUrl)}" />`,
      `<updated>${xml(record.local_last_observed_time)}</updated>`,
      `<published>${xml(`${observed}T00:00:00Z`)}</published>`,
      `<summary>${xml(summary)}</summary>`,
      "</entry>",
    ].join("");
  });
  const body = [
    '<?xml version="1.0" encoding="utf-8"?>',
    '<feed xmlns="http://www.w3.org/2005/Atom">',
    "<id>urn:breachgazette:notifications</id>",
    "<title>Breach Gazette public notifications</title>",
    `<link href="${xml(homeUrl)}" />`,
    `<link href="${xml(feedUrl)}" rel="self" type="application/atom+xml" />`,
    `<updated>${xml(publication.generated_at)}</updated>`,
    "<subtitle>Privacy-minimised official public notification records. Entries are source records, not declarations of unique incidents.</subtitle>",
    ...entries,
    "</feed>",
  ].join("");
  return new Response(body, {
    headers: {
      "Content-Type": "application/atom+xml; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
};
