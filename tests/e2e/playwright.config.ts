import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

/**
 * 《织梦》E2E suite. Expects the app to be running (scripts/dev.sh).
 *   ZM_WEB   frontend origin (default http://localhost:3000)
 *   ZM_API   backend origin  (default http://localhost:8000)
 *   ZM_MODE  "fallback" | "real" — only affects timeouts / strictness of the 5s AC-1 check.
 * 真实模式下后端必须以 ZM_DISABLE_IMAGE=1 启动（scripts/dev.sh 默认如此），E2E 不触发真实插画生成（成本约束）。
 */
const real = (process.env.ZM_MODE ?? "auto") === "real";
// 登录态文件按运行隔离：同一 worktree 里可能有多个 Playwright 同时跑（不同端口/后端），共用 .auth/state.json 会互相覆盖。
// 主进程先定下路径，worker 继承环境变量。
process.env.ZM_E2E_STATE ??= path.join(os.tmpdir(), `zm-e2e-state-${process.pid}.json`);
process.env.ZM_DISABLE_IMAGE ??= "1"; // 供 helpers 检查 /api/health 时参考

export default defineConfig({
  testDir: ".",
  // feat/auth：ZM_AUTH_REQUIRED=1 时以 QA 用户登录（见 global-setup.ts）；auth.spec.ts 自己用空状态
  globalSetup: "./global-setup.ts",
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
    storageState: process.env.ZM_E2E_STATE,
  },
  projects: [
    { name: "ac", testIgnore: /(demo|mobile)\.spec\.ts/, use: { ...devices["Desktop Chrome"], channel: "chrome", viewport: { width: 1440, height: 900 } } },
    { name: "mobile", testMatch: /mobile\.spec\.ts/, use: { ...devices["Pixel 7"], channel: "chrome" } },
    { name: "demo", testMatch: /demo\.spec\.ts/, use: { channel: "chrome", viewport: { width: 1440, height: 900 } } },
  ],
});
