import { defineConfig, devices } from "@playwright/test";

/**
 * 《织梦》E2E suite. Expects the app to be running (scripts/dev.sh).
 *   ZM_WEB   frontend origin (default http://localhost:3000)
 *   ZM_API   backend origin  (default http://localhost:8000)
 *   ZM_MODE  "fallback" | "real" — only affects timeouts / strictness of the 5s AC-1 check.
 * 真实模式下后端必须以 ZM_DISABLE_IMAGE=1 启动（scripts/dev.sh 默认如此），E2E 不触发真实插画生成（成本约束）。
 */
const real = (process.env.ZM_MODE ?? "auto") === "real";
process.env.ZM_DISABLE_IMAGE ??= "1"; // 供 helpers 检查 /api/health 时参考

export default defineConfig({
  testDir: ".",
  testMatch: /.*\.spec\.ts/,
  timeout: real ? 600_000 : 180_000,
  expect: { timeout: real ? 90_000 : 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }], ["json", { outputFile: "test-results/results.json" }]],
  use: {
    baseURL: process.env.ZM_WEB ?? "http://localhost:3000",
    channel: "chrome",
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    viewport: { width: 1440, height: 900 },
    acceptDownloads: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    { name: "ac", testIgnore: /(demo|mobile)\.spec\.ts/, use: { ...devices["Desktop Chrome"], channel: "chrome", viewport: { width: 1440, height: 900 } } },
    { name: "mobile", testMatch: /mobile\.spec\.ts/, use: { ...devices["Pixel 7"], channel: "chrome" } },
    { name: "demo", testMatch: /demo\.spec\.ts/, use: { channel: "chrome", viewport: { width: 1440, height: 900 } } },
  ],
});
