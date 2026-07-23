import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

const inPages = process.env.GITHUB_ACTIONS === "true";

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
