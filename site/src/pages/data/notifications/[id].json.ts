import type { APIRoute } from "astro";
import { getSearchManifest, getSearchPartition } from "../../../lib/data";

export const prerender = true;

export function getStaticPaths() {
  return getSearchManifest().partitions.map((partition) => ({
    params: { id: partition.asset },
    props: { id: partition.id },
  }));
}

export const GET: APIRoute = ({ props }) =>
  new Response(JSON.stringify(getSearchPartition(String(props.id))), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=31536000, immutable",
      "X-Content-Type-Options": "nosniff",
    },
  });
