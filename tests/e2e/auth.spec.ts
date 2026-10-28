/**
 * feat/auth 账号 E2E（契约：API.md「用户系统接口契约」+ TEAM.md「账号/鉴权 QA 契约」v1.4-draft2；页面 testid 以前端实际实现为准，见 TESTIDS.md）
 *   注册 A → 登出 → 登录 A → 创建世界 → 个人中心「我的作品」可见 → 登出 → 注册/登录 B → 看不到 A 的世界（列表、
 *   直接打开链接、API 均 404）→ 退出后 /me 跳转登录页、/api/auth/me 未登录。
 * 后端或前端尚未就绪时整体 skip（原因写在 skip 信息里）。兜底模式运行，不触发真实生图/配音。
 */
import { test, expect, type Page } from "@playwright/test";
import { createAndEnter, el } from "./helpers";

test.use({ storageState: { cookies: [], origins: [] } }); // 从未登录状态开始
test.describe.configure({ mode: "serial" });

const PW = "Zm-QA-pass-2026!";
const uid = () => Math.random().toString(16).slice(2, 10);
const A = { username: `qa_a_${uid()}`, nickname: `测试甲${uid().slice(0, 3)}` };
const B = { username: `qa_b_${uid()}`, nickname: `测试乙${uid().slice(0, 3)}` };
let worldId = "";
let worldTitle = "";

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await ctx.newPage();
  const me = await page.request.get("/api/auth/me");
  if (me.status() === 404) {
    await ctx.close();
    test.skip(true, "后端尚未实现用户系统（/api/auth/me → 404）：等待 织梦-后端");
    return;
  }
  const res = await page.goto("/register");
  const ready = res?.ok() && (await page.getByTestId("register-form").count()) > 0;
  await ctx.close();
  test.skip(!ready, "前端注册页 /register 未就绪（缺 data-testid=register-form）：等待 织梦-前端");
});

async function register(page: Page, u: { username: string; nickname: string }) {
  await page.goto("/register");
  await el(page, "register-username", page.getByLabel("账号")).first().fill(u.username);
  await el(page, "register-nickname", page.getByLabel("昵称")).first().fill(u.nickname);
  await el(page, "register-password", page.getByLabel(/^密码/)).first().fill(PW);
  const confirm = page.getByTestId("register-confirm");
  if (await confirm.count()) await confirm.fill(PW);
  await el(page, "register-submit", page.getByRole("button", { name: /注册/ })).first().click();
  await expectSignedIn(page, u.nickname);
}

async function login(page: Page, u: { username: string; nickname: string }) {
  await page.goto("/login");
  await el(page, "login-username", page.getByLabel("账号")).first().fill(u.username);
  await el(page, "login-password", page.getByLabel("密码")).first().fill(PW);
  await el(page, "login-submit", page.getByRole("button", { name: /^登录$/ })).first().click();
  await expectSignedIn(page, u.nickname);
}

async function expectSignedIn(page: Page, nickname: string) {
  await expect(el(page, "user-nickname").first()).toHaveText(nickname, { timeout: 20_000 });
  const me = await (await page.request.get("/api/auth/me")).json();
  expect(me.authenticated, "/api/auth/me after sign-in").toBe(true);
}

async function logout(page: Page) {
  await el(page, "user-menu-btn").first().click();
  await el(page, "user-menu-logout", page.getByRole("menuitem", { name: /退出|登出/ })).first().click();
  await expect(el(page, "auth-login-link").first()).toBeVisible({ timeout: 20_000 });
  expect((await page.request.get("/api/auth/me")).status(), "/api/auth/me after logout").toBe(401);
  const cookies = await page.context().cookies();
  expect(cookies.filter((c) => c.name.startsWith("zm_") && c.value), "zm_* cookies cleared").toHaveLength(0);
}

async function openWorks(page: Page) {
  await page.goto("/me?tab=works");
  await expect(page.getByTestId("me-page")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("works-loading")).toHaveCount(0, { timeout: 20_000 });
}

test("注册 → 登出 → 登录 → 创建世界 → 个人中心可见", async ({ page }) => {
  await register(page, A);
  await logout(page);
  await login(page, A);
  worldId = await createAndEnter(page);
  const w = await page.request.get(`/api/worlds/${worldId}`);
  expect(w.ok()).toBeTruthy();
  const world = await w.json();
  worldTitle = world.title;
  if ("owner_id" in world) expect(world.owner_id).not.toBe("u_demo");
  await openWorks(page);
  await expect(page.getByTestId("work-item").filter({ hasText: worldTitle })).toHaveCount(1);
  await page.screenshot({ path: "../../docs/screens/auth-01-me-works.png" });
  await logout(page);
});

test("另一用户登录后看不到 A 的世界（个人中心 / 直达链接 / API）", async ({ page }) => {
  test.skip(!worldId, "上一用例未创建世界");
  await register(page, B);
  await logout(page);
  await login(page, B);
  await openWorks(page);
  await expect(page.getByTestId("work-item").filter({ hasText: worldTitle })).toHaveCount(0);
  const list = await (await page.request.get("/api/worlds")).json();
  expect(list.map((x: { id: string }) => x.id)).not.toContain(worldId);
  for (const p of [`/api/worlds/${worldId}`, `/api/worlds/${worldId}/turns`, `/api/worlds/${worldId}/export`]) {
    expect((await page.request.get(p)).status(), p).toBe(404);
  }
  await page.goto(`/play/${worldId}`);
  await expect(page.getByText(/找不到|不存在/).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(worldTitle)).toHaveCount(0);
  await page.screenshot({ path: "../../docs/screens/auth-02-other-user-404.png" });
});

test("退出后个人中心需要重新登录", async ({ page }) => {
  await login(page, B);
  await logout(page);
  await page.goto("/me");
  await expect(page).toHaveURL(/\/login\?next=/, { timeout: 20_000 });
  await expect(page.getByTestId("login-form")).toBeVisible();
});

test("错误密码给出中文提示，不登录", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("login-username").fill(A.username);
  await page.getByTestId("login-password").fill("Wrong-pass-999");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("login-error")).toContainText(/用户名或密码错误|账号或密码错误/);
  expect((await page.request.get("/api/auth/me")).status()).toBe(401);
});

test("重复注册同一账号提示已被注册", async ({ page }) => {
  await page.goto("/register");
  await page.getByTestId("register-username").fill(A.username);
  await page.getByTestId("register-nickname").fill("重复");
  await page.getByTestId("register-password").fill(PW);
  if (await page.getByTestId("register-confirm").count()) await page.getByTestId("register-confirm").fill(PW);
  await page.getByTestId("register-submit").click();
  await expect(page.getByText(/已被注册|已存在/).first()).toBeVisible();
});
