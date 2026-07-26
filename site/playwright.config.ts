import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  timeout: 30_000,
  retries: 0,
  ...(process.env.CI ? { workers: 1 } : {}),
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  use: {
    baseURL: "http://127.0.0.1:41733",
    trace: "retain-on-failure",
  },
  webServer: {
    command:
      "BREACHGAZETTE_TEST_BUILD=1 " +
      "BREACHGAZETTE_SITE_DATA_DIR=../tests/fixtures/site " +
      "npm run preview -- --host 127.0.0.1 --port 41733",
    port: 41733,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
