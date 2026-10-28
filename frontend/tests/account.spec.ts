/**
 * 账号 / 登录 / 个人中心（mock，契约 v1.4-draft2 + AUTH-QA-2 规则）。
 * 覆盖：字段校验、服务端错误按 field 落位、429 倒计时、?next= 回跳与开放重定向防护、受保护路由（auth_required
 * 与演示模式）、顶栏下拉与退出、token_expired 单次共享 refresh + 重试（含回合流）、refresh 失败跳登录、
 * 个人中心各分区、移动端。ZM_SHOTS=1 时把截图写到 docs/screens/auth-*.png。
 */
import { expect, test, type Page } from "@playwright/test";
import { WORLD_ID, mockApi, sse, fixtures, type Json } from "./mock-api";
import { PASSWORD, defaultPrefs, makeUser, mockAuth, shot, signedIn } from "./auth-mock";

const setup = async (page: Page) => {
  const st = await mockApi(page);
  return st;
};
const field = (page: Page, id: string) => page.getByTestId(`${id}-error`);

test.describe("注册", () => {
  test("字段校验：中文提示，规则与后端一致（字母开头、3–20 位、密码 8–64 且含字母数字）", async ({ page }) => {
    await setup(page);
    const auth = await mockAuth(page);
    await page.goto("/register");
    await expect(page.getByTestId("register-form")).toBeVisible();
    await page.getByTestId("register-submit").click();
    await expect(field(page, "register-username")).toHaveText("请输入用户名");
    await expect(field(page, "register-nickname")).toHaveText("请输入昵称");
    await expect(field(page, "register-password")).toHaveText("请输入密码");
    await expect(field(page, "register-confirm")).toHaveText("请再次输入密码");
    await expect(page.getByTestId("register-username")).toBeFocused();

    const u = page.getByTestId("register-username");
    for (const [v, msg] of [
      ["1abc", "用户名需以字母开头"],
      ["_abc", "用户名需以字母开头"],
      ["ab", "用户名长度需为 3–20 位"],
      ["a".repeat(21), "用户名长度需为 3–20 位"],
      ["ab-c", "用户名只能包含字母、数字和下划线"],
      ["Admin", "这个用户名是保留名，请换一个"],
    ]) {
      await u.fill(v);
      await expect(field(page, "register-username")).toHaveText(msg);
    }
    await u.fill("a1_b");
    await expect(field(page, "register-username")).toHaveCount(0);

    const pw = page.getByTestId("register-password");
    for (const [v, msg] of [
      ["abc12", "密码至少 8 位"],
      ["abcdefgh", "密码需同时包含字母和数字"],
      ["12345678", "密码需同时包含字母和数字"],
      ["a1".repeat(32) + "x", "密码最多 64 位"],
      ["a1_b", "密码至少 8 位"],
    ]) {
      await pw.fill(v);
      await expect(field(page, "register-password")).toHaveText(msg);
    }
    await pw.fill("a".repeat(62) + "12"); // exactly 64 is fine
    await expect(field(page, "register-password")).toHaveCount(0);
    await pw.fill("Weave2026dream");
    await expect(page.getByTestId("password-strength")).toContainText("密码强度");
    await page.getByTestId("register-email").fill("not-an-email");
    await page.getByTestId("register-email").blur();
    await expect(field(page, "register-email")).toHaveText("邮箱格式不正确");
    await page.getByTestId("register-confirm").fill("Weave2026dreaM");
    await page.getByTestId("register-confirm").blur();
    await expect(field(page, "register-confirm")).toHaveText("两次输入的密码不一致");
    await shot(page, "register-errors");
    expect(auth.count("POST", "/auth/register")).toBe(0); // never sent while invalid
  });

  test("服务端错误按 field 落位；成功后已登录并进入个人中心", async ({ page }) => {
    await setup(page);
    const taken = makeUser({ username: "lin_xiaoyu" });
    const auth = await mockAuth(page, { users: [{ user: taken, password: PASSWORD }] });
    await page.goto("/register");
    await shot(page, "register");
    await page.getByTestId("register-username").fill("Lin_Xiaoyu");
    await page.getByTestId("register-nickname").fill("小雨");
    await page.getByTestId("register-email").fill("new@example.com");
    await page.getByTestId("register-password").fill("Weave2026dream");
    await page.getByTestId("register-confirm").fill("Weave2026dream");
    await page.getByTestId("register-submit").click();
    await expect(field(page, "register-username")).toHaveText("该用户名已被注册");
    await expect(page.getByTestId("register-username")).toBeFocused();

    await page.getByTestId("register-username").fill("xiaoyu2");
    await page.getByTestId("register-submit").click();
    await expect(page).toHaveURL(/\/me$/);
    await expect(page.getByTestId("user-nickname")).toHaveText("小雨");
    await expect(page.getByTestId("me-nickname")).toHaveText("小雨");
    const sent = auth.calls.find((c) => c.path === "/auth/register" && c.body?.username === "xiaoyu2")!.body!;
    expect(sent).toEqual({ username: "xiaoyu2", nickname: "小雨", password: "Weave2026dream", email: "new@example.com" });
  });

  test("注册 429：按 retry_after 倒计时并禁用提交", async ({ page }) => {
    await setup(page);
    await mockAuth(page, { rateLimit: new Map([["POST /auth/register", 2]]) });
    await page.goto("/register");
    await page.getByTestId("register-username").fill("yun_he");
    await page.getByTestId("register-nickname").fill("云鹤");
    await page.getByTestId("register-password").fill("Weave2026dream");
    await page.getByTestId("register-confirm").fill("Weave2026dream");
    await page.getByTestId("register-submit").click();
    await expect(page.getByTestId("register-error")).toContainText("尝试次数过多");
    await expect(page.getByTestId("register-submit")).toBeDisabled();
    await expect(page.getByTestId("register-submit")).toHaveText(/请 \d 秒后再试/);
    await expect(page.getByTestId("register-submit")).toBeEnabled({ timeout: 4000 });
    await expect(page.getByTestId("register-submit")).toHaveText("注册并登录");
  });
});

test.describe("登录", () => {
  test("用户名或密码错误；429 倒计时；用邮箱登录并回跳 next", async ({ page }) => {
    await setup(page);
    const user = makeUser();
    const auth = await mockAuth(page, { users: [{ user, password: PASSWORD }] });
    await page.goto("/login?next=%2Fme%3Ftab%3Dworks");
    await shot(page, "login");
    await page.getByTestId("login-submit").click();
    await expect(field(page, "login-username")).toHaveText("请输入用户名或邮箱");
    await expect(field(page, "login-password")).toHaveText("请输入密码");

    await page.getByTestId("login-username").fill("lin_xiaoyu");
    await page.getByTestId("login-password").fill("wrong-pass-1");
    await page.getByTestId("login-submit").click();
    await expect(page.getByTestId("login-error")).toHaveText("用户名或密码错误");
    await shot(page, "login-error");

    auth.rateLimit.set("POST /auth/login", 3);
    await page.getByTestId("login-submit").click();
    await expect(page.getByTestId("login-submit")).toBeDisabled();
    await expect(page.getByTestId("login-cooldown")).toBeVisible();
    await expect(page.getByTestId("login-submit")).toHaveText(/请 [1-3] 秒后再试/);
    await expect(page.getByTestId("login-submit")).toBeEnabled({ timeout: 5000 });

    await page.getByTestId("login-username").fill("LIN@example.com");
    await page.getByTestId("login-password").fill(PASSWORD);
    await page.getByTestId("login-submit").click();
    await expect(page).toHaveURL(/\/me\?tab=works$/);
    await expect(page.getByTestId("me-panel-works")).toBeVisible();
    const sent = auth.calls.filter((c) => c.path === "/auth/login").pop()!.body;
    expect(sent).toEqual({ login: "LIN@example.com", password: PASSWORD, remember: true });
  });

  for (const bad of ["//evil.example", "https://evil.example/x", "/\\evil.example", "javascript:alert(1)", "/api/auth/logout", "/login"]) {
    test(`开放重定向防护：next=${bad} 回到首页`, async ({ page }) => {
      await setup(page);
      await signedIn(page); // already signed in → /login immediately follows next
      await page.goto(`/login?next=${encodeURIComponent(bad)}`);
      await expect(page).toHaveURL((u) => u.pathname === "/" && !u.search, { timeout: 10_000 });
    });
  }
});

test.describe("受保护路由", () => {
  test("auth_required=true：未登录访问 /me 与其它页面都跳 /login?next=，登录后回到原处", async ({ page }) => {
    await setup(page);
    const user = makeUser();
    await mockAuth(page, { authRequired: true, users: [{ user, password: PASSWORD }] });
    await page.goto("/me?tab=prefs");
    await expect(page).toHaveURL(/\/login\?next=%2Fme%3Ftab%3Dprefs$/);
    await page.goto("/saves");
    await expect(page).toHaveURL(/\/login\?next=%2Fsaves$/);
    await expect(page.getByTestId("demo-banner")).toHaveCount(0);
    await page.getByTestId("login-username").fill(user.username);
    await page.getByTestId("login-password").fill(PASSWORD);
    await page.getByTestId("login-submit").click();
    await expect(page).toHaveURL(/\/saves$/);
  });

  test("演示模式（auth_required=false）：不强制登录，显示演示账号提示；资料编辑要求登录", async ({ page }) => {
    await setup(page);
    await mockAuth(page);
    await page.goto("/me");
    await expect(page).toHaveURL(/\/me$/);
    await expect(page.getByTestId("demo-banner")).toContainText("当前为演示账号");
    await expect(page.getByTestId("me-nickname")).toHaveText("演示账号");
    await expect(page.getByTestId("me-demo")).toBeVisible();
    await expect(page.getByTestId("stat-card-worlds")).toContainText("7");
    await page.getByTestId("me-tab-profile").click();
    await expect(page.getByTestId("me-login-required")).toBeVisible();
    await page.getByTestId("me-tab-security").click();
    await expect(page.getByTestId("me-login-required")).toBeVisible();
    await expect(page.getByTestId("auth-login-link")).toHaveAttribute("href", /\/login\?next=%2Fme/);
    await shot(page, "demo-mode");
  });

  test("演示账号不能关闭未成年人模式（demo_readonly）", async ({ page }) => {
    await setup(page);
    const auth = await mockAuth(page);
    auth.demoPrefs.minor_mode = true;
    await page.goto("/me?tab=prefs");
    await page.getByTestId("prefs-minor-mode").click();
    await page.getByTestId("prefs-minor-password").fill("anything1");
    await page.getByTestId("prefs-minor-submit").click();
    await expect(field(page, "prefs-minor-password")).toContainText("演示账号");
    await expect(page.getByTestId("prefs-minor-mode")).toBeChecked();
  });
});

test.describe("会话", () => {
  test("顶栏下拉：个人中心 / 退出登录（204，不解析 JSON；清掉本地当前世界）", async ({ page }) => {
    await setup(page);
    const auth = await signedIn(page);
    await page.goto("/");
    await expect(page.getByTestId("user-nickname")).toHaveText("林小雨");
    await page.getByTestId("user-menu-btn").click();
    await expect(page.getByTestId("user-menu")).toBeVisible();
    await shot(page, "user-menu");
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("user-menu")).toHaveCount(0);
    await page.getByTestId("user-menu-btn").click();
    await page.getByTestId("user-menu-profile").click();
    await expect(page).toHaveURL(/\/me$/);
    await page.getByTestId("user-menu-btn").click();
    await page.getByTestId("user-menu-logout").click();
    await expect(page.getByTestId("auth-login-link")).toBeVisible();
    await expect(page.getByTestId("auth-register-link")).toBeVisible();
    await expect(page).toHaveURL((u) => u.pathname === "/");
    expect(auth.count("POST", "/auth/logout")).toBe(1);
    expect(await page.evaluate(() => localStorage.getItem("zhimeng.currentWorld"))).toBeNull();
  });

  test("token_expired：并发请求共用一次 refresh，然后各自重试一次", async ({ page }) => {
    await setup(page);
    const auth = await signedIn(page, {}, { expired: true });
    let worldGets = 0;
    page.on("request", (q) => {
      if (q.method() === "GET" && new URL(q.url()).pathname === `/api/worlds/${WORLD_ID}`) worldGets++;
    });
    await page.goto("/me");
    await expect(page.getByTestId("stat-card-turns")).toContainText("86");
    await expect(page.getByTestId("user-nickname")).toHaveText("林小雨");
    expect(auth.count("POST", "/auth/refresh")).toBe(1);
    // every /auth/me got 401 token_expired then a retry (dev StrictMode may run the session check twice)
    expect(auth.count("GET", "/auth/me") % 2).toBe(0);
    expect(worldGets).toBeGreaterThanOrEqual(2); // the top-bar world chip raced it and retried on the same refresh
  });

  test("refresh 失败：视为登出，跳登录并保留 next", async ({ page }) => {
    await setup(page);
    const auth = await signedIn(page);
    await page.goto("/me?tab=works");
    await expect(page.getByTestId("works-list")).toBeVisible();
    auth.expired = true;
    auth.refreshOk = false;
    await page.getByTestId("me-tab-learning").click();
    await expect(page).toHaveURL(/\/login\?next=%2Fme%3Ftab%3Dlearning$/);
    await expect(page.getByTestId("login-expired")).toBeVisible();
    expect(auth.count("POST", "/auth/refresh")).toBe(1);
  });

  test("回合流：建立前遇到 token_expired 先 refresh 再重试，流正常进行", async ({ page }) => {
    const st = await setup(page);
    const w = fixtures.world as Json;
    const turn = { ...(fixtures.turns[0] as Json), id: "t_after_refresh", index: 2, narration: "门外的雨声渐渐停了。", action: "推门" };
    st.turnStream = () =>
      sse([
        ["token", { text: "门外的雨声渐渐停了。" }],
        ["options", { options: [{ id: "o1", text: "继续" }] }],
        ["done", { turn, state: w.state }],
      ]);
    const auth = await signedIn(page);
    await page.goto(`/play/${WORLD_ID}`);
    await expect(page.locator('article[data-turn="1"]')).toBeVisible();
    auth.expired = true;
    const posts: number[] = [];
    page.on("request", (q) => {
      if (q.method() === "POST" && q.url().endsWith(`/worlds/${WORLD_ID}/turns`)) posts.push(Date.now());
    });
    await page.getByRole("textbox").last().fill("推门");
    await page.keyboard.press("Enter");
    await expect(page.locator('article[data-turn="2"]')).toContainText("门外的雨声渐渐停了");
    expect(auth.count("POST", "/auth/refresh")).toBe(1);
    expect(posts.length).toBe(2);
  });
});

test.describe("个人中心", () => {
  test("概览：统计卡片、最近世界、最近学习", async ({ page }) => {
    await setup(page);
    await signedIn(page);
    await page.goto("/me");
    await expect(page.getByTestId("me-tab-overview")).toHaveAttribute("aria-selected", "true");
    for (const [k, n] of [
      ["worlds", "7"],
      ["saves", "6"],
      ["turns", "86"],
      ["memories", "233"],
      ["cards", "11"],
      ["assets", "29"],
    ])
      await expect(page.getByTestId(`stat-card-${k}`)).toContainText(n);
    await expect(page.getByTestId("overview-recent").getByTestId("work-item")).toHaveCount(3);
    await expect(page.getByTestId("overview-learning")).toContainText("赤壁");
    await shot(page, "me-overview", true);
  });

  test("统计加载失败显示错误与重试", async ({ page }) => {
    await setup(page);
    let fail = true;
    await signedIn(page, {}, { override: (m, p) => (p === "/users/me/stats" && fail ? [500, { detail: "boom" }] : undefined) });
    await page.goto("/me");
    await expect(page.getByTestId("stats-error")).toContainText("服务暂时繁忙");
    fail = false;
    await page.getByTestId("stats-error").getByRole("button", { name: "重试" }).click();
    await expect(page.getByTestId("stat-card-worlds")).toBeVisible();
  });

  test("个人资料：昵称/简介保存、服务端 field 错误、头像裁剪上传与恢复默认、改邮箱需密码", async ({ page }) => {
    await setup(page);
    const auth = await signedIn(page);
    await page.goto("/me?tab=profile");
    await expect(page.getByTestId("profile-avatar")).toHaveText("林");

    await page.getByTestId("profile-nickname").fill("");
    await page.getByTestId("profile-save").click();
    await expect(field(page, "profile-nickname")).toHaveText("请输入昵称");
    await page.getByTestId("profile-nickname").fill("林小雨·夜航");
    await page.getByTestId("profile-bio").fill("这里有违禁词");
    await page.getByTestId("profile-save").click();
    await expect(field(page, "profile-bio")).toHaveText("简介包含不适宜的内容，请修改");
    await page.getByTestId("profile-bio").fill("在雾港等一艘夜船。");
    await page.getByTestId("profile-save").click();
    await expect(page.getByTestId("user-nickname")).toHaveText("林小雨·夜航");
    await expect(page.getByTestId("me-bio")).toHaveText("在雾港等一艘夜船。");

    // avatar: type check, crop dialog, upload (multipart "file"), then remove
    await page.getByTestId("profile-avatar-input").setInputFiles({ name: "a.gif", mimeType: "image/gif", buffer: Buffer.from("GIF89a") });
    await expect(page.getByTestId("profile-avatar-error")).toHaveText("头像仅支持 PNG、JPG 或 WebP 图片");
    await page.getByTestId("profile-avatar-input").setInputFiles(`${__dirname}/fixtures/avatar.png`);
    await expect(page.getByTestId("avatar-crop")).toBeVisible();
    await page.getByTestId("avatar-zoom").fill("1.6");
    await shot(page, "avatar-crop");
    await page.getByTestId("avatar-crop-save").click();
    await expect(page.getByTestId("avatar-crop")).toHaveCount(0);
    await expect(page.getByTestId("profile-avatar")).toHaveAttribute("src", /\/api\/static\/avatars\//);
    await expect(page.getByTestId("user-avatar")).toHaveAttribute("src", /\/api\/static\/avatars\//);
    expect(auth.count("POST", "/users/me/avatar")).toBe(1);
    await shot(page, "me-profile", true);
    await page.getByTestId("profile-avatar-remove").click();
    await expect(page.getByTestId("profile-avatar")).toHaveText("林");

    await page.getByTestId("profile-email").fill("night@example.com");
    await page.getByTestId("profile-email-save").click();
    await expect(field(page, "profile-email-password")).toHaveText("修改邮箱需要输入当前密码");
    await page.getByTestId("profile-email-password").fill("nope12345");
    await page.getByTestId("profile-email-save").click();
    await expect(field(page, "profile-email-password")).toHaveText("当前密码不正确");
    await page.getByTestId("profile-email-password").fill(PASSWORD);
    await page.getByTestId("profile-email-save").click();
    await expect(page.getByTestId("profile-email-password")).toHaveCount(0);
    expect(auth.me()!.email).toBe("night@example.com");
  });

  test("账号安全：校验、当前密码错误、成功（204）、429", async ({ page }) => {
    await setup(page);
    const auth = await signedIn(page);
    await page.goto("/me?tab=security");
    await page.getByTestId("password-submit").click();
    await expect(field(page, "password-current")).toHaveText("请输入当前密码");
    await expect(field(page, "password-new")).toHaveText("请输入密码");
    await page.getByTestId("password-current").fill("wrong-pass-1");
    await page.getByTestId("password-new").fill("wrong-pass-1");
    await page.getByTestId("password-confirm").fill("wrong-pass-1");
    await page.getByTestId("password-submit").click();
    await expect(field(page, "password-new")).toHaveText("新密码不能与当前密码相同");
    await page.getByTestId("password-new").fill("Lantern2026night");
    await page.getByTestId("password-confirm").fill("Lantern2026night");
    await page.getByTestId("password-submit").click();
    await expect(field(page, "password-current")).toHaveText("当前密码不正确");
    await shot(page, "me-security", true);

    auth.rateLimit.set("POST /users/me/password", 2);
    await page.getByTestId("password-current").fill(PASSWORD);
    await page.getByTestId("password-submit").click();
    await expect(page.getByTestId("password-cooldown")).toBeVisible();
    await expect(page.getByTestId("password-submit")).toBeDisabled();
    await expect(page.getByTestId("password-submit")).toBeEnabled({ timeout: 4000 });
    await page.getByTestId("password-submit").click();
    await expect(page.getByTestId("password-done")).toBeVisible();
    await expect(page.getByTestId("password-current")).toHaveValue("");
    expect(auth.users[0].password).toBe("Lantern2026night");
    await expect(page.getByTestId("security-account")).toContainText("lin@example.com");
  });

  test("我的作品：列表、筛选、继续、导入标记", async ({ page }) => {
    await setup(page);
    await signedIn(page);
    await page.goto("/me?tab=works");
    await expect(page.getByTestId("work-item")).toHaveCount(4);
    await expect(page.getByTestId("works-filter-all")).toContainText("4");
    await page.getByTestId("works-filter-education").click();
    await expect(page.getByTestId("work-item")).toHaveCount(1);
    await page.getByTestId("works-filter-ended").click();
    await expect(page.getByTestId("work-item")).toHaveCount(1);
    await expect(page.getByTestId("work-item")).toContainText("导入");
    await page.getByTestId("works-filter-all").click();
    await shot(page, "me-works", true);
    await page.getByTestId("work-continue").first().click();
    await expect(page).toHaveURL(new RegExp(`/play/${WORLD_ID}$`));
  });

  test("我的作品：空状态", async ({ page }) => {
    await setup(page);
    await signedIn(page, {}, { override: (m, p) => (p === "/worlds" ? [200, []] : undefined) });
    await page.goto("/me?tab=works");
    await expect(page.getByTestId("works-empty")).toBeVisible();
  });

  test("学习记录：小结要点、分页加载更多、空状态", async ({ page }) => {
    await setup(page);
    const items = Array.from({ length: 23 }, (_, i) => makeLearn(i));
    await signedIn(page, {}, { learning: items as never });
    await page.goto("/me?tab=learning");
    await expect(page.getByTestId("learning-item")).toHaveCount(20);
    await expect(page.getByTestId("learning-total")).toContainText("共 23 个学习世界");
    await expect(page.getByTestId("learning-summary").first()).toContainText("要点 0");
    await page.getByTestId("learning-more").click();
    await expect(page.getByTestId("learning-item")).toHaveCount(23);
    await expect(page.getByTestId("learning-more")).toHaveCount(0);
  });

  test("学习记录：截图用真实样例 + 空状态", async ({ page }) => {
    await setup(page);
    const auth = await signedIn(page);
    await page.goto("/me?tab=learning");
    await expect(page.getByTestId("learning-item")).toHaveCount(2);
    await expect(page.getByTestId("learning-summary")).toContainText("赤壁之战发生在公元 208 年");
    await expect(page.getByTestId("learning-summary-btn").nth(1)).toHaveText("生成学习小结");
    await shot(page, "me-learning", true);
    auth.learning = [];
    await page.reload();
    await expect(page.getByTestId("learning-empty")).toBeVisible();
  });

  test("偏好设置：PATCH 局部更新；关闭未成年人模式需要密码", async ({ page }) => {
    await setup(page);
    const auth = await signedIn(page);
    await page.goto("/me?tab=prefs");
    await expect(page.getByTestId("prefs-sync")).toContainText("已保存到账号");
    await page.getByTestId("prefs-tts").click();
    await expect(page.getByTestId("prefs-autoplay")).toBeDisabled();
    expect(auth.calls.filter((c) => c.method === "PATCH").pop()!.body).toEqual({ tts_enabled: false });
    await page.getByTestId("prefs-god-view").click();
    await expect(page.getByRole("navigation", { name: "主导航" }).getByText("上帝视角")).toHaveCount(0);

    await page.getByTestId("prefs-minor-mode").click(); // on: no password
    await expect(page.getByTestId("prefs-rating-teen")).toBeDisabled();
    expect(auth.me()!.preferences.minor_mode).toBe(true);
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem("zhimeng.prefs") ?? "{}").minorMode)).toBe(true);

    await page.getByTestId("prefs-minor-mode").click(); // off: asks for the password
    await expect(page.getByTestId("prefs-minor-confirm")).toBeVisible();
    await expect(page.getByTestId("prefs-minor-mode")).toBeChecked();
    await page.getByTestId("prefs-minor-password").fill("bad-pass-1");
    await page.getByTestId("prefs-minor-submit").click();
    await expect(field(page, "prefs-minor-password")).toHaveText("当前密码不正确");
    await expect(page.getByTestId("prefs-minor-mode")).toBeChecked();
    await page.getByTestId("prefs-minor-password").fill(PASSWORD);
    await page.getByTestId("prefs-minor-submit").click();
    await expect(page.getByTestId("prefs-minor-confirm")).toHaveCount(0);
    await expect(page.getByTestId("prefs-minor-mode")).not.toBeChecked();
    expect(auth.calls.filter((c) => c.method === "PATCH").pop()!.body).toEqual({ minor_mode: false, current_password: PASSWORD });
    await page.getByTestId("prefs-grade").fill("初二");
    await page.getByTestId("prefs-edu-save").click();
    await expect.poll(() => auth.me()!.preferences.education.grade).toBe("初二");
    await shot(page, "me-prefs", true);
  });
});

test.describe("v1.4 联调修订", () => {
  test("预设头像：PATCH avatar_url=preset:<key>，恢复默认清空", async ({ page }) => {
    await setup(page);
    const auth = await signedIn(page);
    await page.goto("/me?tab=profile");
    await page.getByTestId("avatar-preset-crane").click();
    await expect(page.getByTestId("avatar-preset-crane")).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("profile-avatar")).toHaveText("鹤");
    await expect(page.getByTestId("user-avatar")).toHaveText("鹤");
    expect(auth.calls.filter((c) => c.method === "PATCH").pop()!.body).toEqual({ avatar_url: "preset:crane" });
    await page.getByTestId("profile-avatar-remove").click();
    await expect(page.getByTestId("profile-avatar")).toHaveText("林");
    expect(auth.calls.filter((c) => c.method === "PATCH").pop()!.body).toEqual({ avatar_url: null });
    expect(auth.count("DELETE", "/users/me/avatar")).toBe(0);
  });

  test("演示账号（已登录 demo）：资料/头像与改密码直接引导登录，带 next 回跳", async ({ page }) => {
    await setup(page);
    await signedIn(page, { username: "demo", nickname: "演示账号", is_demo: true, email: null, bio: "" });
    await page.goto("/me?tab=security");
    await expect(page.getByTestId("me-login-required")).toBeVisible();
    await expect(page.getByTestId("password-form")).toHaveCount(0);
    await expect(page.getByTestId("me-login-required-login")).toHaveAttribute("href", "/login?next=%2Fme%3Ftab%3Dsecurity");
    await page.getByTestId("me-tab-profile").click();
    await expect(page.getByTestId("profile-avatar-input")).toHaveCount(0);
    await expect(page.getByTestId("me-login-required-login")).toHaveAttribute("href", "/login?next=%2Fme%3Ftab%3Dprofile");
  });

  test("auth_required=1：首页可访问；点「造化」先去登录，登录回来草稿还在", async ({ page }) => {
    await setup(page);
    const user = makeUser();
    const auth = await mockAuth(page, { authRequired: true, users: [{ user, password: PASSWORD }] });
    await page.goto("/");
    await expect(page).toHaveURL((u) => u.pathname === "/");
    await expect(page.getByTestId("home-login-hint")).toBeVisible();
    await page.getByRole("textbox").first().fill("雨夜的江南小镇，我是刚到的说书人");
    await page.getByTestId("generate-btn").click();
    await expect(page).toHaveURL(/\/login\?next=%2F$/);
    await page.getByTestId("login-username").fill(user.username);
    await page.getByTestId("login-password").fill(PASSWORD);
    await page.getByTestId("login-submit").click();
    await expect(page).toHaveURL((u) => u.pathname === "/");
    await expect(page.getByRole("textbox").first()).toHaveValue("雨夜的江南小镇，我是刚到的说书人");
    await expect(page.getByTestId("home-login-hint")).toHaveCount(0);
    expect(auth.calls.some((c) => c.path === "/worlds/generate")).toBe(false);
  });

  test("auth_required=1：受保护页面路由层直接跳登录（游玩/上帝/记忆/教育/存档/设置/个人中心）", async ({ page }) => {
    await setup(page);
    await mockAuth(page, { authRequired: true });
    for (const p of [`/play/${WORLD_ID}`, `/preview/${WORLD_ID}`, `/god/${WORLD_ID}`, `/memory/${WORLD_ID}`, "/education", "/saves", "/settings", "/me"]) {
      await page.goto(p);
      await expect(page, p).toHaveURL(`/login?next=${encodeURIComponent(p)}`);
    }
    await page.goto("/register");
    await expect(page.getByTestId("register-form")).toBeVisible();
  });

  test("演示模式下写操作意外 401（非 token_expired）也统一跳登录", async ({ page }) => {
    await setup(page);
    await mockAuth(page);
    await page.route("**/api/worlds/import", (r) =>
      r.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "请先登录", code: "unauthorized" }) }),
    );
    await page.goto("/saves");
    await expect(page.getByTestId("demo-banner")).toBeVisible();
    await page.getByTestId("import-input").setInputFiles({
      name: "save.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify({ format: "zhimeng-save", world: fixtures.world, turns: [] })),
    });
    await expect(page).toHaveURL("/login?next=%2Fsaves");
  });

  const settingsRoutes = async (page: Page, w: Json, clampHeader: string | null) => {
    await page.route(`**/api/worlds/${WORLD_ID}/settings`, (r) =>
      r.fulfill({
        status: 200,
        contentType: "application/json",
        headers: clampHeader ? { "X-ZM-Clamped": clampHeader } : {},
        body: JSON.stringify(w),
      }),
    );
    await page.route(`**/api/worlds/${WORLD_ID}`, (r) =>
      r.request().method() === "GET"
        ? r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(w) })
        : r.fallback(),
    );
  };

  test("世界设置：账号已开未成年人模式时，相关开关置灰并说明（不假装能关）", async ({ page }) => {
    await setup(page);
    await signedIn(page, { preferences: { ...defaultPrefs(), minor_mode: true, rating: "all" } });
    await settingsRoutes(page, { ...(fixtures.world as Json), minor_mode: true, rating: "all" }, null);
    await page.goto("/settings");
    await expect(page.getByTestId("account-minor-note")).toBeVisible();
    await expect(page.getByTestId("minor-mode-toggle")).toBeChecked();
    await expect(page.getByTestId("minor-mode-toggle")).toBeDisabled();
    await expect(page.getByTestId("world-minor-toggle")).toBeChecked();
    await expect(page.getByTestId("world-minor-toggle")).toBeDisabled();
  });

  test("世界设置：收到 X-ZM-Clamped 时以服务端返回值回显，并用中文说明原因", async ({ page }) => {
    await setup(page);
    await mockAuth(page); // demo browsing: the account floor is only known to the server
    const w = { ...(fixtures.world as Json), minor_mode: true, rating: "all" };
    await settingsRoutes(page, w, "minor_mode");
    await page.goto("/settings");
    await expect(page.getByTestId("world-minor-toggle")).toBeChecked();
    await page.getByTestId("world-minor-toggle").click();
    await expect(page.getByTestId("settings-clamped")).toContainText("已按账号的未成年人模式设置");
    await expect(page.getByTestId("settings-clamped")).toContainText("不能关闭未成年人模式");
    await expect(page.getByTestId("world-minor-toggle")).toBeChecked(); // the server's value, not the click
  });
});

test.describe("移动端", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("未登录顶栏显示登录/注册；登录后头像菜单可用，个人中心标签横向排列", async ({ page }) => {
    await setup(page);
    const auth = await mockAuth(page, { users: [{ user: makeUser(), password: PASSWORD }] });
    await page.goto("/");
    await expect(page.getByTestId("auth-login-link")).toBeVisible();
    await expect(page.getByTestId("auth-register-link")).toBeVisible();
    await shot(page, "mobile-topbar-anon");
    auth.current = auth.users[0].user.id;
    await page.goto("/me");
    await expect(page.getByTestId("user-menu-btn")).toBeVisible();
    await expect(page.getByTestId("user-nickname")).toBeHidden(); // avatar only on narrow screens
    const tabs = page.getByRole("tablist");
    const [a, b] = await Promise.all([
      page.getByTestId("me-tab-overview").boundingBox(),
      page.getByTestId("me-tab-profile").boundingBox(),
    ]);
    expect(Math.abs(a!.y - b!.y)).toBeLessThan(4); // one row
    await expect(tabs).toBeVisible();
    await expect(page.getByTestId("stat-card-worlds")).toBeVisible();
    await shot(page, "mobile-me", true);
    await page.getByTestId("user-menu-btn").click();
    await expect(page.getByTestId("user-menu")).toBeInViewport();
    await shot(page, "mobile-menu");
    await page.goto("/login");
    await shot(page, "mobile-login");
  });
});

function makeLearn(i: number) {
  return {
    world_id: `w_edu_${i}`,
    title: `学习世界 ${i}`,
    subject: "语文",
    grade: "初二",
    status: "active",
    turns: 3 + i,
    cards: i % 4,
    created_at: "2026-10-20T08:00:00+00:00",
    updated_at: new Date(Date.UTC(2026, 9, 27, 12) - i * 3600_000).toISOString(),
    summary: i % 2 ? null : { key_points: [`要点 ${i}`], reflection: "", source: "fallback", turn_count: 3, generated_at: "2026-10-27T12:00:00+00:00" },
  };
}
