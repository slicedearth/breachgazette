import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

const testBuild = process.env.BREACHGAZETTE_TEST_BUILD === "1";

function canonicalSite() {
  const configured = process.env.BREACHGAZETTE_SITE_URL;
  if (!configured) {
    if (testBuild) return "https://breachgazette.invalid";
    throw new Error("BREACHGAZETTE_SITE_URL is required for a production build");
  }
  const parsed = new URL(configured);
  if (
    parsed.protocol !== "https:" ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error(
      "BREACHGAZETTE_SITE_URL must be an HTTPS origin without credentials, path, query, or fragment",
    );
  }
  return parsed.origin;
}

export default defineConfig({
  output: "static",
  site: canonicalSite(),
  base: "/",
  integrations: [sitemap()],
  build: {
    inlineStylesheets: "auto",
  },
  vite: {
    build: {
      assetsInlineLimit: 0,
    },
  },
});
