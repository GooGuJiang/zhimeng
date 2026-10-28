/**
 * Screenshots against a REAL fallback backend (ZM_FORCE_FALLBACK=1 → no model / image / voice calls), run on
 * demand only:  ZM_REAL_SHOTS=1 ZM_DEMO_PW=<demo password of that backend's data dir> ZM_WEB=… pnpm test:mock real-shots
 * Seeds the demo account through the API (a few fallback worlds, turns, one learning world + its summary) so
 * the 个人中心 lists and stats show real data, then captures docs/screens/auth-*.png. Main shape: ZM_AUTH_REQUIRED=1.
 */
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const ON = process.env.ZM_REAL_SHOTS === "1";
const DEMO_PW = process.env.ZM_DEMO_PW ?? "";
const OUT = path.resolve(__dirname, "../../docs/screens");
const shot = (page: Page, name: string, fullPage = false) => page.screenshot({ path: `${OUT}/auth-${name}.png`, fullPage });

// no page errors (hydration mismatches etc.) on any captured page
const pageErrors: string[] = [];
test.beforeEach(({ page }) => {
  page.on("pageerror", (e) => pageErrors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) pageErrors.push(m.text());
  });
});
test.afterEach(() => {
  expect(pageErrors.splice(0)).toEqual([]);
});

test.skip(!ON || !DEMO_PW, "real-backend screenshots: set ZM_REAL_SHOTS=1 and ZM_DEMO_PW");
test.describe.configure({ mode: "serial" });
test.setTimeout(240_000);

function sseData(text: string): Record<string, unknown>[] {
  return text
    .split(/\n\n+/)
    .map((b) => b.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("\n"))
    .filter(Boolean)
    .map((d) => {
      try {
        return JSON.parse(d) as Record<string, unknown>;
      } catch {
        return {};
      }
    });
}
const worldIdFrom = (text: string) => {
  for (const d of sseData(text)) {
    const w = (d.world as { id?: string } | undefined)?.id ?? (typeof d.world_id === "string" ? d.world_id : undefined);
    if (w) return w;
    if (typeof d.id === "string" && "mode" in d) return d.id;
  }
  throw new Error(`no world id in stream: ${text.slice(0, 300)}`);
};

async function play(req: APIRequestContext, id: string, actions: string[]) {
  for (const a of actions) {
    const r = await req.post(`/api/worlds/${id}/turns`, { data: { action: a, client_turn_id: `shot-${Date.now()}-${Math.random()}` } });
    expect(r.ok(), `turn ${a}`).toBeTruthy();
    await r.text();
  }
}

async function login(page: Page, login: string, pw: string) {
  await page.goto("/login");
  await page.getByTestId("login-username").fill(login);
  await page.getByTestId("login-password").fill(pw);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("user-menu-btn")).toBeVisible({ timeout: 20_000 });
}

test("登录 / 注册页（未登录，含校验错误）", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("auth-login-link")).toBeVisible();
  await shot(page, "home-anon");
  await page.goto("/register");
  await expect(page.getByTestId("register-form")).toBeVisible();
  await shot(page, "register");
  await page.getByTestId("register-username").fill("1abc");
  await page.getByTestId("register-password").fill("abcdefgh");
  await page.getByTestId("register-confirm").fill("abcdefgh1");
  await page.getByTestId("register-submit").click();
  await expect(page.getByTestId("register-username-error")).toHaveText("用户名需以字母开头");
  await shot(page, "register-errors");
  await page.goto("/login?next=%2Fme");
  await shot(page, "login");
  await page.getByTestId("login-username").fill("demo");
  await page.getByTestId("login-password").fill("not-the-password-1");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("login-error")).toHaveText("用户名或密码错误");
  await shot(page, "login-error");
});

test("演示账号：造数据后截个人中心（概览 / 作品 / 学习 / 偏好 / 下拉 / 移动端）", async ({ page }) => {
  await login(page, "demo", DEMO_PW);
  const req = page.request;
  const have = (await (await req.get("/api/worlds")).json()) as unknown[];
  if (have.length < 3) {
    for (const [prompt, genre, tone] of [
      ["一个民国上海滩的侦探故事，我是报社记者", "悬疑", "沉郁"],
      ["盛唐长安的西市，我是刚到京城的胡商学徒", "历史", "轻快"],
      ["海底图书馆里，书会在夜里偷偷改写结局", "奇幻", "诡谲"],
    ]) {
      const r = await req.post("/api/worlds/generate", { data: { prompt, genre, tone, length: "short", language: "zh", mode: "story" } });
      expect(r.ok()).toBeTruthy();
      const id = worldIdFrom(await r.text());
      await req.post(`/api/worlds/${id}/confirm`);
      await play(req, id, ["四处看看", "去找最近的线索"]);
    }
    const e = await req.post("/api/education/generate", {
      data: { source_text: "晋太元中，武陵人捕鱼为业。缘溪行，忘路之远近。忽逢桃花林，夹岸数百步，中无杂树，芳草鲜美，落英缤纷。", title: "桃花源记", subject: "语文", grade: "初中", minor_mode: true },
    });
    expect(e.ok()).toBeTruthy();
    const eid = worldIdFrom(await e.text());
    await req.post(`/api/worlds/${eid}/confirm`);
    await play(req, eid, ["沿着溪水向前走", "走进桃花林深处"]);
    await (await req.get(`/api/worlds/${eid}/education/summary`)).text();
  }

  await page.goto("/me");
  await expect(page.getByTestId("stat-card-worlds")).toBeVisible();
  await shot(page, "me-overview", true);
  await page.getByTestId("me-tab-works").click();
  await expect(page.getByTestId("work-item").first()).toBeVisible();
  await shot(page, "me-works", true);
  await page.getByTestId("me-tab-learning").click();
  await expect(page.getByTestId("learning-item").first()).toBeVisible();
  await shot(page, "me-learning", true);
  await page.getByTestId("me-tab-prefs").click();
  await expect(page.getByTestId("prefs-sync")).toContainText("已保存到账号");
  await shot(page, "me-prefs", true);
  await page.getByTestId("me-tab-security").click();
  await expect(page.getByTestId("me-login-required")).toBeVisible();
  await shot(page, "me-security-demo");
  await page.getByTestId("me-tab-overview").click();
  await page.getByTestId("user-menu-btn").click();
  await expect(page.getByTestId("user-menu")).toBeVisible();
  await page.waitForTimeout(600);
  await shot(page, "user-menu");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/me");
  await expect(page.getByTestId("stat-card-worlds")).toBeVisible();
  await shot(page, "mobile-me");
  await page.getByTestId("user-menu-btn").click();
  await page.waitForTimeout(600); // dropdown fade-in
  await shot(page, "mobile-menu");
});

test("自己的账号：资料（预设头像）与账号安全", async ({ page }) => {
  const name = `lin${Date.now().toString(36).slice(-6)}`;
  await page.goto("/register");
  await page.getByTestId("register-username").fill(name);
  await page.getByTestId("register-nickname").fill("林小雨");
  await page.getByTestId("register-email").fill(`${name}@example.com`);
  await page.getByTestId("register-password").fill("Weave2026dream");
  await page.getByTestId("register-confirm").fill("Weave2026dream");
  await page.getByTestId("register-submit").click();
  await expect(page).toHaveURL(/\/me$/, { timeout: 20_000 });
  await page.goto("/me?tab=profile");
  await page.getByTestId("avatar-preset-bamboo").click();
  await expect(page.getByTestId("profile-avatar")).toHaveText("竹");
  await page.getByTestId("profile-bio").fill("喜欢民国悬疑和江南雨夜。");
  await page.getByTestId("profile-save").click();
  await expect(page.getByTestId("me-bio")).toHaveText("喜欢民国悬疑和江南雨夜。");
  await page.waitForTimeout(3500); // let the 「资料已保存」 toast go
  await shot(page, "me-profile", true);
  await page.getByTestId("me-tab-security").click();
  await page.getByTestId("password-current").fill("Wrong2026pass");
  await page.getByTestId("password-new").fill("Lantern2026night");
  await page.getByTestId("password-confirm").fill("Lantern2026night");
  await page.getByTestId("password-submit").click();
  await expect(page.getByTestId("password-current-error")).toBeVisible();
  await shot(page, "me-security", true);
  await page.context().clearCookies();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  await expect(page.getByTestId("login-form")).toBeVisible();
  await shot(page, "mobile-login");
});
