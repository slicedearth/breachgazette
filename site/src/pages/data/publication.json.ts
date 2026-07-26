import type { APIRoute } from "astro";
import { getPublication } from "../../lib/data";

export const prerender = true;

export const GET: APIRoute = () => {
  const publication = getPublication();
  const identity = {
    schema_version: publication.schema_version,
    generated_at: publication.generated_at,
    record_counts: publication.manifest.record_counts,
    publication_checksum: publication.manifest.publication_checksum,
    publication_checksum_algorithm:
      publication.manifest.publication_checksum_algorithm,
    publication_checksum_scope:
      publication.manifest.publication_checksum_scope,
    published_corrections: publication.corrections.length,
    max_public_corrections: publication.manifest.max_public_corrections,
    update_digest: publication.update_digest,
    search_manifest: `${import.meta.env.BASE_URL}data/notifications/manifest.json`,
  };
  return new Response(JSON.stringify(identity), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=0, must-revalidate",
      "X-Content-Type-Options": "nosniff",
    },
  });
};
