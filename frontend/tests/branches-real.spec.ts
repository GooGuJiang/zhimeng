/**
 * Real fallback-backend e2e for 角色分支 / 剧情脉络 (v1.5).
 *   ZM_REAL_BRANCHES=1 ZM_WEB=http://127.0.0.1:3422 ZM_API=http://127.0.0.1:8420 ZM_SHOTS=1
 *     pnpm exec playwright test -c tests branches-real.spec.ts --output=/tmp/fe-pw-branch-real
 * Backend must be ZM_FORCE_FALLBACK=1 ZM_DISABLE_IMAGE=1 — no real image / voice / model calls.
 */
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const RUN = process.env.ZM_REAL_BRANCHES === "1";
const API = (process.env.ZM_API ?? "http://127.0.0.1:8420").replace(/\/$/, "");
const WEB = process.env.ZM_WEB ?? "http://127.0.0.1:3422";
const PROMPT = "织梦演示：迷雾小镇的古钟";
const SCREENS = process.env.ZM_SHOTS ? path.resolve(__dirname, "../../docs/screens") : "";

test.skip(!RUN, "set ZM_REAL_BRANCHES=1 (and ZM_WEB / ZM_API) to run against the fallback backend");

async function shot(page: Page, name: string, fullPage = false) {
  if (SCREENS) {
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SCREENS}/branch-${name}.png`, fullPage });
  }
}

async function seedWorld(request: APIRequestContext) {
  const headers = { origin: WEB, "content-type": "application/json" };
  const created = await request.post(`${API}/api/worlds`, {
    headers,
    data: { prompt: PROMPT, language: "zh", mode: "story" },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const world = await created.json();
  const conf = await request.post(`${API}/api/worlds/${world.id}/confirm`, { headers });
  expect(conf.ok(), await conf.text()).toBeTruthy();
  return world as { id: string; title: string };
}

test("兜底演示：迷雾小镇古钟 — 选项带提示、另选后脉络可见两条线", async ({ page, request }) => {
  const world = await seedWorld(request);
  expect(world.title).toBeTruthy();
  await page.goto(`/play/${world.id}`);
  await expect(page.getByTestId("narration")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("branch-choices")).toBeVisible();
  const buttons = page.getByTestId("option-btn");
  await expect(buttons).toHaveCount(3);
  await expect(page.getByTestId("option-hint")).toHaveCount(3);
  await expect(buttons.nth(0)).toContainText("走进酒馆和老乔聊聊");
  await expect(page.getByTestId("free-input")).toBeVisible();
  await shot(page, "choices-opening", true);

  await buttons.filter({ hasText: "走进酒馆和老乔聊聊" }).click();
  await expect(page.getByTestId("narration-latest")).toContainText("老乔", { timeout: 20_000 });
  await expect(page.getByTestId("option-btn").filter({ hasText: "当面质疑老乔" })).toBeVisible();
  await expect(page.getByTestId("option-hint").first()).toBeVisible();
  await page.getByTestId("branch-choices").scrollIntoViewIfNeeded();
  await shot(page, "after-first-choice");

  await page.getByTestId("option-btn").filter({ hasText: "当面质疑老乔" }).click();
  await expect(page.getByTestId("narration-latest")).toContainText(/脸色一沉|说漏/, { timeout: 20_000 });

  await page.getByTestId("branch-open").click();
  const view = page.getByTestId("branch-view");
  await expect(view).toBeVisible();
  await expect(view.getByTestId("branch-node-current")).toContainText("当面质疑老乔");
  await expect(view.getByTestId("branch-readonly")).toHaveCount(0);
  await page.waitForTimeout(450);
  await shot(page, "tree-one-line");

  // 回到「走进酒馆」那一步（index=1），不是开局
  await view.locator('[data-testid="branch-node"][data-index="1"]').getByTestId("branch-rewind").click();
  await expect(page.getByTestId("branch-confirm")).toContainText("走出一条新的故事线");
  await page.getByTestId("branch-confirm-ok").click();
  await expect(view).toHaveCount(0);
  await expect(page.getByTestId("option-btn").filter({ hasText: "相信老乔，答应帮忙" })).toBeVisible();
  await expect(page.getByTestId("option-taken")).toBeVisible();
  await page.getByTestId("branch-choices").scrollIntoViewIfNeeded();
  await shot(page, "rewound-to-opening");

  await page.getByTestId("option-btn").filter({ hasText: "相信老乔，答应帮忙" }).click();
  await expect(page.getByTestId("narration-latest")).toContainText(/松了口气|肯信我/, { timeout: 20_000 });
  await expect(page.getByTestId("branch-forked")).toBeVisible();

  await page.getByTestId("branch-open").click();
  await expect(page.getByTestId("branch-view")).toBeVisible();
  await expect(page.getByTestId("branch-open")).toContainText("2 条线");
  await expect(page.getByTestId("branch-view")).toContainText(/已经走出 2 条/);
  await expect(page.getByTestId("branch-view")).toContainText("当面质疑老乔");
  await expect(page.getByTestId("branch-view")).toContainText("相信老乔，答应帮忙");
  await expect(page.getByTestId("branch-view")).toContainText("支线1");
  await expect(page.getByTestId("branch-node-current")).toContainText("相信老乔，答应帮忙");
  await page.waitForTimeout(450);
  await shot(page, "tree-two-lines");
});

test("从开局页走完整生成确认，开局选项与自由输入可见", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("prompt-input").fill(PROMPT);
  await page.getByTestId("generate-btn").click();
  await expect(page.getByTestId("world-preview")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("confirm-world-btn").click();
  await expect(page.getByTestId("branch-choices")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("option-btn")).toHaveCount(3);
  await expect(page.getByTestId("option-hint").first()).toContainText(/老乔|钟楼|新消息/);
  await expect(page.getByTestId("free-input")).toBeVisible();
  await page.getByTestId("branch-open").click();
  await expect(page.getByTestId("branch-view")).toBeVisible();
  await expect(page.getByTestId("branch-readonly")).toHaveCount(0);
  await page.waitForTimeout(450);
  await shot(page, "opening-tree");
});
