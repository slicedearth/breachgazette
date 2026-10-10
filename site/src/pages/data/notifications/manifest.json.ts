import type { APIRoute } from "astro";
import { getSearchManifestJSON } from "../../../lib/data";

export const prerender = true;

export const GET: APIRoute = () =>
  new Response(getSearchManifestJSON(), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
      "X-Content-Type-Options": "nosniff",
    },
  });
