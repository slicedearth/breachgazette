import type { APIRoute } from "astro";

export const GET: APIRoute = ({ site }) => {
  if (!site) throw new Error("A canonical site URL is required for robots.txt");
  const sitemap = new URL(
    `${import.meta.env.BASE_URL}sitemap-index.xml`,
    site,
  ).toString();
  return new Response(`User-agent: *\nAllow: /\nSitemap: ${sitemap}\n`, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
};
