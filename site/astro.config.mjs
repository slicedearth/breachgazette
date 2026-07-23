import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

const inPages = process.env.BREACHGAZETTE_PAGES_BUILD === "1";

export default defineConfig({
  output: "static",
  site: inPages ? "https://slicedearth.github.io" : "https://breachgazette.invalid",
  base: inPages ? "/breachgazette" : "/",
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
