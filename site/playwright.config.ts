import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:41733",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run preview -- --host 127.0.0.1 --port 41733",
    port: 41733,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
