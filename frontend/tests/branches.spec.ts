/**
 * Character branch choices + 剧情脉络 (评审改版 2026-11-16).
 * Uses the in-memory branch engine so a second path can be taken without the real backend.
 */
import { expect, test, type Page } from "@playwright/test";
import { WORLD_ID, mockApi } from "./mock-api";
import { bootBranchEngine, forkTurnStream, handleBranchRoute } from "./branch-mock";
import optionsFx from "./fixtures/options.json";

import path from "node:path";
const SCREENS = process.env.ZM_SHOTS ? path.resolve(__dirname, "../../docs/screens") : "";

async function shot(page: Page, name: string, fullPage = false) {
  if (SCREENS) await page.screenshot({ path: `${SCREENS}/branch-${name}.png`, fullPage });
}

async function readyPlay(page: Page) {
  const st = await mockApi(page);
  const eng = bootBranchEngine(st, optionsFx.options);
  st.options = { options: eng.currentOptions };
  st.turns = []; // start at the opening so the first four choices are visible
  eng.tree.current_node_id = "opening";
  for (const n of eng.tree.nodes) n.current = n.id === "opening";
  // drop any imported turns from the fixture so the demo starts at 开局
  eng.tree.nodes = eng.tree.nodes.filter((n) => n.id === "opening");
  eng.tree.lines = [{ id: "line_main", leaf_id: "opening", current: true }];
  eng.currentOptions = st.options.options;
  st.world = { ...st.world, state: { ...(st.world.state as object), turn: 0 } };
  st.turnStream = (body) => forkTurnStream(eng, st, body);
  st.extra = (method, path, body) => handleBranchRoute(eng, st, method, path, body);
  await page.goto(`/play/${WORLD_ID}`);
  await expect(page.getByTestId("narration")).toBeVisible();
  return { st, eng };
}

test("游玩页在开局就给出带后果提示的可点选项，并保留自由输入", async ({ page }) => {
  await readyPlay(page);
  const choices = page.getByTestId("branch-choices");
  await expect(choices).toBeVisible();
  const buttons = page.getByTestId("option-btn");
  await expect(buttons).toHaveCount(3);
  await expect(page.getByTestId("option-hint")).toHaveCount(3);
  await expect(buttons.nth(0)).toContainText("向顾长庚追问细节");
  await expect(page.getByTestId("option-hint").first()).toContainText("尚未公开");
  await expect(page.getByTestId("free-input")).toBeVisible();
  await expect(page.getByTestId("free-input")).toHaveAttribute("placeholder", /写下你自己的行动/);
  await shot(page, "choices-opening", true);
});

test("点击选项即作为本回合行动，故事走向与选项对应；脉络里留下这一步", async ({ page }) => {
  await readyPlay(page);
  await page.getByTestId("option-btn").nth(1).click(); // 调查仓库铁门
  await expect(page.getByTestId("narration-latest")).toContainText("仓库铁门", { timeout: 20_000 });
  await expect(page.getByTestId("option-btn").first()).toContainText(/轮印|这把锁|离开/);
  await expect(page.getByTestId("branch-strip")).toContainText("调查仓库铁门");
  await shot(page, "after-first-choice", true);
});

test("剧情脉络可以看出两条线，并能回到开局另选", async ({ page }) => {
  await readyPlay(page);
  await page.getByTestId("option-btn").nth(1).click();
  await expect(page.getByTestId("narration-latest")).toContainText("仓库铁门", { timeout: 20_000 });

  await page.getByTestId("branch-open").click();
  const view = page.getByTestId("branch-view");
  await expect(view).toBeVisible();
  await expect(view.getByTestId("branch-node-current")).toContainText("调查仓库铁门");
  await expect(view.getByTestId("branch-readonly")).toHaveCount(0);
  await page.waitForTimeout(450);
  await shot(page, "tree-one-line");

  await view.getByTestId("branch-rewind").first().click();
  await expect(page.getByTestId("branch-confirm")).toContainText("走出一条新的故事线");
  await page.getByTestId("branch-confirm-ok").click();
  await expect(view).toHaveCount(0);
  // back at opening choices
  await expect(page.getByTestId("option-btn").first()).toContainText("向顾长庚追问细节");
  await shot(page, "rewound-to-opening", true);

  await page.getByTestId("option-btn").nth(0).click(); // 追问细节 — a different path
  await expect(page.getByTestId("narration-latest")).toContainText("追问细节", { timeout: 20_000 });

  await page.getByTestId("branch-open").click();
  await expect(page.getByTestId("branch-view")).toBeVisible();
  await expect(page.getByTestId("branch-view")).toContainText("调查仓库铁门");
  await expect(page.getByTestId("branch-view")).toContainText("向顾长庚追问细节");
  await expect(page.getByTestId("branch-open")).toContainText("2 条线");
  await expect(page.getByTestId("branch-view")).toContainText(/已经走出 2 条/);
  await expect(page.getByTestId("branch-node-current")).toContainText("向顾长庚追问细节");
  await page.waitForTimeout(450);
  await shot(page, "tree-two-lines");
});

test("后端没有脉络接口时：选项仍可用，脉络为只读单线，不出现技术词", async ({ page }) => {
  await mockApi(page); // default: GET /branches is a linear tree, rewind 404
  await page.goto(`/play/${WORLD_ID}`);
  await expect(page.getByTestId("option-btn").first()).toBeVisible();
  await expect(page.getByTestId("option-hint").first()).toBeVisible();
  await page.getByTestId("branch-open").click();
  await expect(page.getByTestId("branch-view")).toBeVisible();
  await expect(page.getByTestId("branch-readonly")).toBeVisible();
  await expect(page.getByTestId("branch-rewind")).toHaveCount(0);
  const body = await page.getByTestId("branch-view").innerText();
  expect(body).not.toMatch(/agent|LLM|token|option_id|node_id|line_id|API/i);
  await page.waitForTimeout(450);
  await shot(page, "readonly-fallback");
});

test("选择或回顾过程中的失败可以重试；不出现技术术语", async ({ page }) => {
  const st = await mockApi(page);
  const eng = bootBranchEngine(st, optionsFx.options);
  st.options = { options: eng.currentOptions };
  st.turns = [];
  eng.tree.current_node_id = "opening";
  eng.tree.nodes = eng.tree.nodes.filter((n) => n.id === "opening");
  eng.tree.lines = [{ id: "line_main", leaf_id: "opening", current: true }];
  let failRewind = true;
  st.turnStream = (body) => forkTurnStream(eng, st, body);
  st.extra = (method, path, body) => {
    if (path.endsWith("/branches/rewind") && failRewind) {
      failRewind = false;
      return { $http: true, status: 500, body: { detail: "暂时无法回到那一步", code: "server_error" } };
    }
    return handleBranchRoute(eng, st, method, path, body);
  };
  await page.goto(`/play/${WORLD_ID}`);
  await page.getByTestId("option-btn").nth(0).click();
  await expect(page.getByTestId("narration-latest")).toContainText("追问", { timeout: 20_000 });
  await page.getByTestId("branch-open").click();
  await page.getByTestId("branch-rewind").first().click();
  await page.getByTestId("branch-confirm-ok").click();
  await expect(page.getByTestId("branch-view").locator(".notice")).toContainText(/无法回到|繁忙|重试/);
  // retry from the confirm? error is in the dialog; open confirm again after the error
  await expect(page.getByTestId("branch-confirm")).toBeVisible();
  await page.getByTestId("branch-confirm-ok").click();
  await expect(page.getByTestId("option-btn").first()).toContainText("向顾长庚追问细节");
});
