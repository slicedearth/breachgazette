import type { APIRoute } from "astro";
import { getSearchManifest } from "../../../lib/data";

export const prerender = true;

export const GET: APIRoute = () =>
  new Response(JSON.stringify(getSearchManifest()), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
      "X-Content-Type-Options": "nosniff",
    },
  });
