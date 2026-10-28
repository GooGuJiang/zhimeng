/**
 * In-memory account backend for Playwright, following TEAM.md「用户系统接口契约」v1.4-draft2 (+ AUTH-QA-2 rules).
 * Register after `mockApi(page)`: Playwright runs the newest route first, and anything not handled here
 * falls back to mock-api.ts. The browser never sees a token — like the real httpOnly cookies, the session lives
 * in this object (`current`, `expired`).
 */
import path from "node:path";
import type { Page, Route } from "@playwright/test";
import { fixtures } from "./mock-api";

type J = Record<string, unknown>;
export interface Prefs {
  minor_mode: boolean;
  rating: "all" | "teen" | "mature";
  tts_enabled: boolean;
  autoplay_audio: boolean;
  show_god_view: boolean;
  education: { grade: string | null; subject: string | null; auto_summary: boolean };
  language: "zh";
}
export const defaultPrefs = (): Prefs => ({
  minor_mode: false,
  rating: "teen",
  tts_enabled: true,
  autoplay_audio: false,
  show_god_view: true,
  education: { grade: null, subject: null, auto_summary: true },
  language: "zh",
});
export interface MockUser {
  id: string;
  username: string;
  email: string | null;
  nickname: string;
  avatar_url: string | null;
  bio: string;
  preferences: Prefs;
  is_demo: boolean;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
}
export const PASSWORD = "Weave2026dream";

const now = () => new Date().toISOString();
export function makeUser(over: Partial<MockUser> = {}): MockUser {
  return {
    id: `u_${Math.random().toString(16).slice(2, 10)}`,
    username: "lin_xiaoyu",
    email: "lin@example.com",
    nickname: "林小雨",
    avatar_url: null,
    bio: "喜欢民国悬疑和江南雨夜。",
    preferences: defaultPrefs(),
    is_demo: false,
    created_at: "2026-10-19T08:12:00+00:00",
    updated_at: "2026-10-28T07:40:11+00:00",
    last_login_at: "2026-10-28T07:40:11+00:00",
    ...over,
  };
}

const w = fixtures.world as J;
const summary = (id: string, title: string, mode: string, status: string, turn: number, upd: string) => ({
  id,
  title,
  genre: mode === "education" ? "历史" : "悬疑",
  tone: mode === "education" ? "沉静" : "紧张",
  mode,
  turn,
  status,
  created_at: "2026-10-20T08:00:00+00:00",
  updated_at: upd,
});
export const WORLDS = [
  summary(w.id as string, w.title as string, "story", "active", 6, "2026-10-28T07:40:11+00:00"),
  summary("w_edu_1", "赤壁 · 东风起时", "education", "active", 9, "2026-10-27T12:00:00+00:00"),
  { ...summary("w_old", "雾港旧梦", "story", "ended", 31, "2026-10-22T10:00:00+00:00"), origin: "imported" },
  summary("w_draft", "未命名的山城", "story", "draft", 0, "2026-10-21T10:00:00+00:00"),
];
export const LEARNING = [
  {
    world_id: "w_edu_1",
    title: "赤壁 · 东风起时",
    subject: "历史",
    grade: "初二",
    status: "active",
    turns: 9,
    cards: 6,
    created_at: "2026-10-25T08:00:00+00:00",
    updated_at: "2026-10-27T12:00:00+00:00",
    summary: {
      key_points: ["赤壁之战发生在公元 208 年", "孙刘联军以火攻击败曹军", "战后三国鼎立格局初步形成"],
      reflection: "我站在周瑜的船头，第一次明白「天时」为何能左右一场战役。",
      source: "fallback",
      turn_count: 9,
      generated_at: "2026-10-27T12:00:00+00:00",
    },
  },
  {
    world_id: "w_edu_2",
    title: "背影 · 月台上的父亲",
    subject: "语文",
    grade: "初二",
    status: "ended",
    turns: 14,
    cards: 5,
    created_at: "2026-10-23T08:00:00+00:00",
    updated_at: "2026-10-24T12:00:00+00:00",
    summary: null,
  },
];
export const STATS = {
  worlds: { total: 7, story: 5, education: 2, draft: 1, active: 5, ended: 1, imported: 1 },
  saves: { slots: 6, imported: 1 },
  play: {
    turns: 86,
    chapters: 19,
    injected_events: 4,
    offscreen_events: 51,
    memories: 233,
    first_played_at: "2026-10-19T08:12:00+00:00",
    last_played_at: "2026-10-28T07:40:11+00:00",
  },
  assets: { image: 14, audio: 15 },
  learning: { worlds: 2, turns: 23, knowledge_cards: 11, summaries: 1, latest: LEARNING[0] },
  reports_submitted: 0,
  recent_worlds: WORLDS.slice(0, 3),
};

export interface AuthMock {
  /** ZM_AUTH_REQUIRED */
  authRequired: boolean;
  users: { user: MockUser; password: string }[];
  /** id of the signed-in user (the "cookie") */
  current: string | null;
  /** zm_access expired: authed endpoints answer 401 token_expired until a refresh */
  expired: boolean;
  /** whether POST /auth/refresh succeeds */
  refreshOk: boolean;
  /** respond 429 to this "METHOD /path" once per entry with retry_after */
  rateLimit: Map<string, number>;
  /** override a response: return [status, body] or undefined */
  override?: (method: string, path: string, body: J | null) => [number, unknown] | undefined;
  demoPrefs: Prefs;
  learning: typeof LEARNING;
  learningTotal?: number;
  calls: { method: string; path: string; body: J | null }[];
  count: (method: string, path: string) => number;
  me: () => MockUser | null;
}

const DEMO = { id: "u_demo", username: "demo", nickname: "演示账号" };

export async function mockAuth(page: Page, init: Partial<AuthMock> = {}): Promise<AuthMock> {
  const st: AuthMock = {
    authRequired: false,
    users: [],
    current: null,
    expired: false,
    refreshOk: true,
    rateLimit: new Map(),
    demoPrefs: defaultPrefs(),
    learning: LEARNING,
    calls: [],
    count: (m, p) => st.calls.filter((c) => c.method === m && c.path === p).length,
    me: () => st.users.find((u) => u.user.id === st.current)?.user ?? null,
    ...init,
  };
  const send = (r: Route, status: number, body?: unknown) =>
    status === 204
      ? r.fulfill({ status: 204, body: "" })
      : r.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  const err = (r: Route, status: number, code: string, detail: string, extra: J = {}) =>
    send(r, status, { detail, code, ...extra });

  await page.route("**/api/**", async (r) => {
    const url = new URL(r.request().url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = r.request().method();
    let body: J | null = null;
    try {
      body = r.request().postDataJSON() as J;
    } catch {
      body = null;
    }
    const mine =
      path.startsWith("/auth/") || path.startsWith("/users/") || path === "/worlds" || path.startsWith("/static/avatars/");
    if (!mine) {
      // other data endpoints: a pending access-token expiry or a required login applies to them too
      if (st.current && st.expired) return err(r, 401, "token_expired", "登录已过期");
      if (!st.current && st.authRequired && path !== "/health") return err(r, 401, "unauthorized", "请先登录");
      return r.fallback();
    }
    st.calls.push({ method, path, body });

    const ov = st.override?.(method, path, body);
    if (ov) return send(r, ov[0], ov[1]);
    const rl = st.rateLimit.get(`${method} ${path}`);
    if (rl) {
      st.rateLimit.delete(`${method} ${path}`);
      return err(r, 429, "rate_limited", `尝试次数过多，请 ${rl} 秒后再试`, { retry_after: rl });
    }

    if (path.startsWith("/static/avatars/"))
      return r.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        body: `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="100%" height="100%" fill="#2b7259"/><circle cx="128" cy="104" r="48" fill="#f5f0e6"/><rect x="56" y="168" width="144" height="70" rx="35" fill="#f5f0e6"/></svg>`,
      });

    const anon401 = () =>
      err(r, 401, "unauthorized", "请先登录", {
        auth_required: st.authRequired,
        acting_as: st.authRequired ? null : DEMO,
      });

    // ---- public auth endpoints
    if (path === "/auth/me" && method === "GET") {
      if (st.current && st.expired)
        return err(r, 401, "token_expired", "登录已过期", { auth_required: st.authRequired, acting_as: null });
      const u = st.me();
      return u ? send(r, 200, { authenticated: true, user: u, auth_required: st.authRequired }) : anon401();
    }
    if (path === "/auth/refresh" && method === "POST") {
      await new Promise((res) => setTimeout(res, 300)); // lets concurrent callers pile up on one refresh
      if (st.refreshOk && st.me()) {
        st.expired = false;
        return send(r, 200, { user: st.me() });
      }
      st.current = null;
      st.expired = false;
      return err(r, 401, "refresh_invalid", "登录已过期，请重新登录");
    }
    if (path === "/auth/logout" && method === "POST") {
      st.current = null;
      st.expired = false;
      return send(r, 204);
    }
    if (path === "/auth/register" && method === "POST") {
      const b = body as { username: string; password: string; nickname: string; email?: string };
      if (st.users.some((u) => u.user.username.toLowerCase() === b.username.toLowerCase()))
        return err(r, 409, "username_taken", "用户名已被占用", { field: "username" });
      if (b.email && st.users.some((u) => u.user.email === b.email!.toLowerCase()))
        return err(r, 409, "email_taken", "该邮箱已被其他账号使用", { field: "email" });
      if (b.password === "Password123") return err(r, 400, "weak_password", "密码过于常见，请换一个", { field: "password" });
      const user = makeUser({
        username: b.username,
        nickname: b.nickname,
        email: b.email?.toLowerCase() ?? null,
        bio: "",
        created_at: now(),
        updated_at: now(),
        last_login_at: now(),
      });
      st.users.push({ user, password: b.password });
      st.current = user.id;
      return send(r, 201, { user });
    }
    if (path === "/auth/login" && method === "POST") {
      const b = body as { login: string; password: string };
      const l = b.login.toLowerCase();
      const hit = st.users.find(
        (u) => (u.user.username.toLowerCase() === l || u.user.email === l) && u.password === b.password,
      );
      if (!hit) return err(r, 401, "invalid_credentials", "用户名或密码错误");
      hit.user.last_login_at = now();
      st.current = hit.user.id;
      return send(r, 200, { user: hit.user });
    }

    // ---- authenticated endpoints
    if (st.current && st.expired) return err(r, 401, "token_expired", "登录已过期");
    const u = st.me();
    const demoOk = !u && !st.authRequired; // ZM_AUTH_REQUIRED=0: anonymous acts as demo for reads/prefs
    if (path === "/worlds" && method === "GET") return u || demoOk ? send(r, 200, WORLDS) : anon401();
    if (path === "/users/me/stats") return u || demoOk ? send(r, 200, STATS) : anon401();
    if (path === "/users/me/learning") {
      if (!u && !demoOk) return anon401();
      const limit = Number(url.searchParams.get("limit") ?? 20);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      return send(r, 200, {
        items: st.learning.slice(offset, offset + limit),
        total: st.learningTotal ?? st.learning.length,
        limit,
        offset,
      });
    }
    if (path === "/users/me/preferences") {
      if (!u && !demoOk) return anon401();
      const cur = u ? u.preferences : st.demoPrefs;
      if (method === "GET") return send(r, 200, { preferences: cur });
      const { current_password, education, ...rest } = (body ?? {}) as J & { education?: J };
      if (cur.minor_mode && rest.minor_mode === false) {
        if (!u) return err(r, 403, "demo_readonly", "演示账号不能关闭未成年人模式");
        const pw = st.users.find((x) => x.user.id === u.id)!.password;
        if (current_password !== pw) return err(r, 401, "wrong_password", "当前密码不正确", { field: "current_password" });
      }
      const next = { ...cur, ...rest, education: { ...cur.education, ...(education ?? {}) } } as Prefs;
      if (next.minor_mode) next.rating = "all";
      if (u) u.preferences = next;
      else st.demoPrefs = next;
      return send(r, 200, { preferences: next });
    }
    if (!u) return anon401();
    if (u.is_demo && method !== "GET") return err(r, 403, "demo_readonly", "演示账号不能修改资料");
    if ((path === "/users/me" || path === "/auth/me") && method === "PATCH") {
      const b = (body ?? {}) as {
        nickname?: string;
        bio?: string;
        email?: string | null;
        current_password?: string;
        avatar_url?: string | null;
      };
      if ("avatar_url" in b) {
        if (b.avatar_url !== null && !/^preset:[A-Za-z0-9_-]{1,32}$/.test(String(b.avatar_url)))
          return err(r, 422, "validation_error", "头像只能是预设头像（preset:<key>）或通过上传接口设置", { field: "avatar_url" });
        u.avatar_url = b.avatar_url ?? null;
      }
      if (b.bio && b.bio.includes("违禁")) return err(r, 400, "content_blocked", "简介包含不适宜的内容，请修改", { field: "bio" });
      if ("email" in b) {
        const pw = st.users.find((x) => x.user.id === u.id)!.password;
        if (b.current_password !== pw) return err(r, 401, "wrong_password", "当前密码不正确", { field: "current_password" });
        u.email = b.email ? b.email.toLowerCase() : null;
      }
      if (b.nickname !== undefined) u.nickname = b.nickname;
      if (b.bio !== undefined) u.bio = b.bio;
      u.updated_at = now();
      return send(r, 200, { user: u });
    }
    if (path === "/users/me/password" && (method === "POST" || method === "PUT")) {
      const b = body as { current_password: string; new_password: string };
      const rec = st.users.find((x) => x.user.id === u.id)!;
      if (b.current_password !== rec.password) return err(r, 401, "wrong_password", "当前密码不正确", { field: "current_password" });
      if (b.new_password === rec.password) return err(r, 400, "same_password", "新密码不能与当前密码相同", { field: "new_password" });
      rec.password = b.new_password;
      return send(r, 204);
    }
    if (path === "/users/me/avatar" && method === "POST") {
      u.avatar_url = `/api/static/avatars/${u.id}_${Date.now().toString(36)}.webp`;
      return send(r, 200, { avatar_url: u.avatar_url, user: u });
    }
    if (path === "/users/me/avatar" && method === "DELETE") {
      u.avatar_url = null;
      return send(r, 200, { avatar_url: null, user: u });
    }
    return r.fallback();
  });
  return st;
}

/** Signed-in state with one known user. */
export async function signedIn(page: Page, over: Partial<MockUser> = {}, init: Partial<AuthMock> = {}) {
  const user = makeUser(over);
  return mockAuth(page, { users: [{ user, password: PASSWORD }], current: user.id, ...init });
}

export const SCREENS = process.env.ZM_SHOTS ? path.resolve(__dirname, "../../docs/screens") : "";
export const shot = async (page: Page, name: string, fullPage = false) => {
  if (SCREENS) await page.screenshot({ path: `${SCREENS}/auth-${name}.png`, fullPage });
};
