import { expect, type Locator, type Page, type APIRequestContext } from "@playwright/test";

export const API = process.env.ZM_API ?? "http://localhost:8000";
export const DEMO_PROMPT = "一个民国上海滩的侦探故事，我是报社记者";
export const AI_LABEL = "内容由AI生成";
/** Visible AI badges are hidden by default (user request); set ZM_SHOW_AI_LABEL=1 when the web build used
 *  NEXT_PUBLIC_ZM_SHOW_AI_LABEL=1. The API fields ai_generated/ai_label are asserted either way. */
export const SHOW_AI_LABEL = ["1", "true", "yes", "on"].includes((process.env.ZM_SHOW_AI_LABEL ?? "").toLowerCase());
export const REAL = (process.env.ZM_MODE ?? "") === "real";

/** data-testid first, then any of the fallbacks (visible text / role). */
export function el(page: Page | Locator, id: string, ...fallbacks: (string | RegExp | Locator)[]): Locator {
  let loc = page.getByTestId(id);
  for (const f of fallbacks) {
    const alt = typeof f === "string" || f instanceof RegExp ? page.getByText(f) : f;
    loc = loc.or(alt);
  }
  return loc;
}

export async function health(request: APIRequestContext) {
  const r = await request.get(`${API}/api/health`);
  expect(r.ok()).toBeTruthy();
  return (await r.json()) as { status: string; llm: boolean; models: Record<string, string> };
}

export function promptInput(page: Page) {
  return el(page, "prompt-input", page.getByPlaceholder(/一句话|主题|世界/));
}

export function generateBtn(page: Page) {
  return el(page, "generate-btn", page.getByRole("button", { name: /造化/ }));
}

/** Home → type prompt → 造化 → preview. Returns ms until preview visible. */
export async function generateWorld(page: Page, prompt = DEMO_PROMPT): Promise<number> {
  await page.goto("/");
  await promptInput(page).first().fill(prompt);
  const t0 = Date.now();
  await generateBtn(page).first().click();
  await expect(el(page, "world-preview").first()).toBeVisible({ timeout: REAL ? 120_000 : 30_000 });
  await expect(el(page, "initial-conflict").first()).toBeVisible();
  return Date.now() - t0;
}

export async function confirmWorld(page: Page) {
  await el(page, "confirm-world-btn", page.getByRole("button", { name: /进入世界|确认|开始/ })).first().click();
  await expect(freeInput(page)).toBeVisible({ timeout: 30_000 });
  await waitIdle(page);
}

export async function createAndEnter(page: Page, prompt = DEMO_PROMPT) {
  await generateWorld(page, prompt);
  await confirmWorld(page);
  return currentWorldId(page);
}

export function freeInput(page: Page) {
  return el(page, "free-input", page.getByPlaceholder(/行动|输入|做什么/)).first();
}

/** 回合失败时（API.md: error → 未提交，可重试）点「重试」的次数，测试结束会写进注解。 */
export const retryLog: string[] = [];

async function idleOnce(page: Page) {
  // thinking indicator appears then disappears; tolerate it never appearing (instant fallback)
  const ind = page.getByTestId("thinking-indicator");
  await expect(ind).toHaveCount(0, { timeout: REAL ? 180_000 : 60_000 });
  await expect(freeInput(page)).toBeEnabled({ timeout: REAL ? 180_000 : 60_000 });
}

export async function waitIdle(page: Page, maxRetries = REAL ? 2 : 0) {
  await idleOnce(page);
  // 用户可见的失败重试：真实模型被限流/断流时，像真实用户一样点「重试」（兜底模式不重试，失败即失败）
  for (let i = 0; i < maxRetries; i++) {
    const retry = page.locator('main [data-testid="retry-btn"]').or(page.getByRole("button", { name: /^重试$/ })).first();
    if (!(await retry.isVisible().catch(() => false))) return;
    retryLog.push(`${new Date().toISOString()} ${page.url()}`);
    await retry.click();
    await page.waitForTimeout(300);
    await idleOnce(page);
  }
}

export async function narrationText(page: Page) {
  return (await el(page, "narration").first().innerText()).trim();
}

export async function playTurn(page: Page, action: string) {
  const before = await narrationText(page);
  await freeInput(page).fill(action);
  await el(page, "send-btn", page.getByRole("button", { name: /发送|行动|提交/ })).first().click();
  await waitIdle(page);
  await expect.poll(async () => (await narrationText(page)).length, { timeout: 60_000 }).toBeGreaterThan(before.length);
}

/** World id from URL (/play/<id>, /world/<id>, ?world=<id>) or localStorage. */
export async function currentWorldId(page: Page): Promise<string> {
  const url = page.url();
  const m = url.match(/(?:world|worlds|play|w|god|preview)\/([A-Za-z0-9_-]{6,})/) ?? url.match(/[?&](?:world|id)=([A-Za-z0-9_-]+)/);
  if (m) return m[1];
  const fromLs = await page.evaluate(() => {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)!;
      const v = localStorage.getItem(k) ?? "";
      const mm = v.match(/"(?:world_id|worldId|id)"\s*:\s*"([A-Za-z0-9_-]{6,})"/) ?? (/world/i.test(k) && /^[A-Za-z0-9_-]{6,}$/.test(v) ? [v, v] : null);
      if (mm) return mm[1];
    }
    return null;
  });
  if (fromLs) return fromLs;
  throw new Error(`cannot determine world id from ${url}`);
}

export async function apiJson<T = any>(request: APIRequestContext, path: string): Promise<T> {
  const r = await request.get(`${API}${path}`);
  expect(r.ok(), `${path} ${r.status()}`).toBeTruthy();
  return (await r.json()) as T;
}

export async function shot(page: Page, name: string) {
  // 等有限时长的 CSS/Web 动画（入场淡入、遮罩）播完；无限循环动画忽略
  await page.waitForFunction(() => document.getAnimations().every((a) => {
    const it = a.effect?.getTiming().iterations;
    return a.playState !== "running" || it === Infinity;
  }), null, { timeout: 8_000 }).catch(() => {});
  await page.screenshot({ path: `../../docs/screens/${name}.png`, fullPage: false });
}
