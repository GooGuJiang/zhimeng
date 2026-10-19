import { defineConfig, devices } from "@playwright/test";

/**
 * Frontend mock regression suite (v1.3 states the fallback backend never produces: pending upgrades,
 * mid-stream safety blocks, post-commit narration replacement). Every /api call is answered by
 * tests/mock-api.ts, so only a running frontend is needed:
 *   ZM_WEB=http://localhost:3000 pnpm test:mock
 */
export default defineConfig({
  testDir: ".",
  testMatch: /.*\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: "../test-results/mock",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.ZM_WEB ?? "http://localhost:3000",
    channel: "chrome",
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
});
