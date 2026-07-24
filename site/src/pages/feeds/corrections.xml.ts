import type { APIRoute } from "astro";
import { getPublication } from "../../lib/data";
import { label } from "../../lib/format";

const xml = (value: string) =>
  value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&apos;");

export const GET: APIRoute = ({ site }) => {
  if (!site) throw new Error("A canonical site URL is required for the corrections feed");
  const publication = getPublication();
  const feedUrl = new URL(
    `${import.meta.env.BASE_URL}feeds/corrections.xml`,
    site,
  ).toString();
  const correctionsUrl = new URL(`${import.meta.env.BASE_URL}corrections/`, site).toString();
  const entries = publication.corrections.slice(0, 50).map((event) => {
    const sourceName = publication.policies[event.source_id]?.name ?? label(event.source_id);
    const entryUrl = `${correctionsUrl}#event-${encodeURIComponent(event.event_id)}`;
    const summary = [
      event.reason,
      ...event.limitations,
      "This entry records an observed official-source change and does not independently establish why the source changed.",
    ].join(" ");
    return [
      "<entry>",
      `<id>${xml(`urn:breachgazette:correction:${event.event_id}`)}</id>`,
      `<title>${xml(`${label(event.event_type)} — ${sourceName}`)}</title>`,
      `<link href="${xml(entryUrl)}" />`,
      `<updated>${xml(event.first_observed_time)}</updated>`,
      `<summary>${xml(summary)}</summary>`,
      "</entry>",
    ].join("");
  });
  const body = [
    '<?xml version="1.0" encoding="utf-8"?>',
    '<feed xmlns="http://www.w3.org/2005/Atom">',
    "<id>urn:breachgazette:corrections</id>",
    "<title>Breach Gazette observed source corrections</title>",
    `<link href="${xml(correctionsUrl)}" />`,
    `<link href="${xml(feedUrl)}" rel="self" type="application/atom+xml" />`,
    `<updated>${xml(publication.generated_at)}</updated>`,
    "<subtitle>Observed changes between complete official-source snapshots. Entries do not independently establish why a source changed.</subtitle>",
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
