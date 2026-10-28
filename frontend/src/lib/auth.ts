/**
 * Accounts — contract: TEAM.md「用户系统接口契约」v1.4-draft2. All endpoints live here.
 * Session = httpOnly cookies `zm_access` (Path=/api) + `zm_refresh` (Path=/api/auth) set by the backend; the
 * browser never reads a token. `request()` sends credentials and refreshes once on 401 `token_expired`.
 */
import { ApiError, request } from "./api";
import type { Rating, WorldSummary } from "./types";
import {
  BIO_MAX,
  EMAIL_MAX,
  EMAIL_RE,
  NICKNAME_LEN,
  PASSWORD_LEN,
  RESERVED_USERNAMES,
  USERNAME_LEN,
  USERNAME_RE,
} from "./authRules";

export interface Preferences {
  minor_mode: boolean;
  rating: Rating;
  tts_enabled: boolean;
  autoplay_audio: boolean;
  show_god_view: boolean;
  education: { grade: string | null; subject: string | null; auto_summary: boolean };
  language: "zh";
}
export interface User {
  id: string;
  username: string;
  email: string | null;
  nickname: string;
  /** "/api/static/avatars/<file>" or null → nickname initial */
  avatar_url: string | null;
  bio: string;
  preferences: Preferences;
  is_demo: boolean;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
}
export interface ActingAs {
  id: string;
  username: string;
  nickname: string;
}
/** GET /auth/me, normalised (200 → signed in; 401 → anonymous with auth_required / acting_as). */
export interface Session {
  user: User | null;
  authRequired: boolean;
  actingAs: ActingAs | null;
}
export interface UserStats {
  worlds: { total: number; story: number; education: number; draft: number; active: number; ended: number; imported: number };
  saves: { slots: number; imported: number };
  play: {
    turns: number;
    chapters: number;
    injected_events: number;
    offscreen_events: number;
    memories: number;
    first_played_at: string | null;
    last_played_at: string | null;
  };
  assets: { image: number; audio: number };
  learning: { worlds: number; turns: number; knowledge_cards: number; summaries: number; latest: LearningRecord | null };
  reports_submitted: number;
  recent_worlds: WorldSummary[];
}
export interface LearningRecord {
  world_id: string;
  title: string;
  subject: string | null;
  grade: string | null;
  status: string;
  turns: number;
  cards: number;
  created_at: string;
  updated_at: string;
  summary: {
    key_points: string[];
    reflection: string;
    source: "llm" | "fallback";
    turn_count: number;
    generated_at: string;
  } | null;
}
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

const unwrapUser = (r: { user?: User } | null | undefined): User => {
  if (!r || !isUser(r.user)) throw new ApiError("服务返回的账号信息不完整，请重试", 0, "bad_response");
  return r.user;
};

export const authApi = {
  async session(): Promise<Session> {
    try {
      const r = await request<{ authenticated?: boolean; user?: User; auth_required?: boolean }>("/auth/me");
      return {
        user: r?.authenticated !== false && isUser(r?.user) ? r.user! : null,
        authRequired: !!r?.auth_required,
        actingAs: null,
      };
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        const b = e.body ?? {};
        return {
          user: null,
          authRequired: !!b.auth_required,
          actingAs: (b.acting_as as ActingAs | null | undefined) ?? null,
        };
      }
      throw e;
    }
  },
  register: (body: { username: string; password: string; nickname: string; email?: string }) =>
    request<{ user: User }>("/auth/register", { method: "POST", json: body }).then(unwrapUser),
  login: (body: { login: string; password: string; remember: boolean }) =>
    request<{ user: User }>("/auth/login", { method: "POST", json: body }).then(unwrapUser),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  updateProfile: (body: {
    nickname?: string;
    bio?: string;
    email?: string | null;
    current_password?: string;
    /** "preset:<key>" (§13.5) or null to clear; uploaded images go through uploadAvatar */
    avatar_url?: string | null;
  }) =>
    request<{ user: User }>("/users/me", { method: "PATCH", json: body }).then(unwrapUser),
  uploadAvatar: (file: Blob, name = "avatar.png") => {
    const fd = new FormData();
    fd.append("file", file, name);
    return request<{ user: User }>("/users/me/avatar", { method: "POST", body: fd, timeout: 60_000 }).then(unwrapUser);
  },
  deleteAvatar: () => request<{ user: User }>("/users/me/avatar", { method: "DELETE" }).then(unwrapUser),
  changePassword: (body: { current_password: string; new_password: string }) =>
    request<void>("/users/me/password", { method: "POST", json: body }),
  getPreferences: () => request<{ preferences: Preferences }>("/users/me/preferences").then((r) => r.preferences),
  patchPreferences: (patch: Partial<Omit<Preferences, "education">> & {
    education?: Partial<Preferences["education"]>;
    current_password?: string;
  }) =>
    request<{ preferences: Preferences }>("/users/me/preferences", { method: "PATCH", json: patch }).then(
      (r) => r.preferences,
    ),
  stats: () => request<UserStats>("/users/me/stats"),
  learning: (limit = 20, offset = 0) => request<Page<LearningRecord>>(`/users/me/learning?limit=${limit}&offset=${offset}`),
  worlds: () => request<WorldSummary[]>("/worlds"),
};

export const isUser = (u: unknown): u is User =>
  !!u && typeof u === "object" && typeof (u as User).id === "string" && typeof (u as User).username === "string";

/* ---------------- validation (rules: lib/authRules.ts — contract §4 + AUTH-QA-2) ---------------- */
export const LIMITS = {
  username: [USERNAME_LEN.min, USERNAME_LEN.max],
  nickname: [NICKNAME_LEN.min, NICKNAME_LEN.max],
  password: [PASSWORD_LEN.min, PASSWORD_LEN.max],
  bio: BIO_MAX,
  email: EMAIL_MAX,
} as const;

export function validateUsername(v: string): string | null {
  const s = v.trim();
  if (!s) return "请输入用户名";
  if (s.length < USERNAME_LEN.min || s.length > USERNAME_LEN.max) return `用户名长度需为 ${USERNAME_LEN.min}–${USERNAME_LEN.max} 位`;
  if (!/^[A-Za-z]/.test(s)) return "用户名需以字母开头";
  if (!USERNAME_RE.test(s)) return "用户名只能包含字母、数字和下划线";
  if ((RESERVED_USERNAMES as readonly string[]).includes(s.toLowerCase())) return "这个用户名是保留名，请换一个";
  return null;
}
export function validateNickname(v: string): string | null {
  const s = v.trim();
  if (!s) return "请输入昵称";
  if ([...s].length > NICKNAME_LEN.max) return `昵称最多 ${NICKNAME_LEN.max} 个字`;
  if (/[\u0000-\u001f\u007f]/.test(s)) return "昵称不能包含控制字符";
  return null;
}
export function validateEmail(v: string, required = false): string | null {
  const s = v.trim();
  if (!s) return required ? "请输入邮箱" : null;
  if (s.length > EMAIL_MAX) return "邮箱太长了";
  if (!EMAIL_RE.test(s)) return "邮箱格式不正确";
  return null;
}
export function validatePassword(v: string, username = "", email = ""): string | null {
  if (!v) return "请输入密码";
  if (v.length < PASSWORD_LEN.min) return `密码至少 ${PASSWORD_LEN.min} 位`;
  if (v.length > PASSWORD_LEN.max) return `密码最多 ${PASSWORD_LEN.max} 位`;
  if (!/[A-Za-z]/.test(v) || !/\d/.test(v)) return "密码需同时包含字母和数字";
  const lower = v.toLowerCase();
  if ((username && lower === username.trim().toLowerCase()) || (email && lower === email.trim().toLowerCase()))
    return "密码不能与用户名或邮箱相同";
  return null;
}
export function validateBio(v: string): string | null {
  return [...v].length > BIO_MAX ? `简介最多 ${BIO_MAX} 字` : null;
}
/** 0–4 rough strength, for the meter only. */
export function passwordStrength(v: string): number {
  if (!v) return 0;
  let n = 0;
  if (v.length >= 8) n++;
  if (v.length >= 12) n++;
  if (/[A-Za-z]/.test(v) && /\d/.test(v)) n++;
  if (/[^A-Za-z0-9]/.test(v) || (/[a-z]/.test(v) && /[A-Z]/.test(v))) n++;
  return Math.min(4, n);
}

/**
 * Server error → where to show it. Contract errors are `{detail (Chinese), code, field?, retry_after?}`;
 * `field` wins, then known codes, then the (already friendly) message.
 */
export function authErrorFor(e: unknown, fieldAlias: Record<string, string> = {}): {
  field?: string;
  message: string;
  retryAfter?: number;
} {
  if (!(e instanceof ApiError)) return { message: "网络连接异常，请稍后重试" };
  const pick = (f?: string) => (f ? (fieldAlias[f] ?? f) : undefined);
  const serverField = typeof e.body?.field === "string" ? (e.body.field as string) : undefined;
  if (e.code === "rate_limited" || e.status === 429)
    return { message: "尝试次数过多，请稍后再试", retryAfter: e.retryAfter ?? 60 };
  if (serverField) return { field: pick(serverField), message: e.message };
  const byCode: Record<string, { field?: string; message: string }> = {
    username_taken: { field: "username", message: "该用户名已被注册，换一个试试，或直接登录" },
    username_reserved: { field: "username", message: "这个用户名是保留名，请换一个" },
    email_taken: { field: "email", message: "该邮箱已被其他账号使用" },
    weak_password: { field: "password", message: e.message || "密码强度不足" },
    same_password: { field: "new_password", message: "新密码不能与当前密码相同" },
    wrong_password: { field: "current_password", message: "当前密码不正确" },
    invalid_password: { field: "current_password", message: "当前密码不正确" },
    invalid_credentials: { message: "用户名或密码错误" },
    demo_readonly: { message: "演示账号不能修改这项设置，请注册自己的账号" },
    content_blocked: { message: e.message || "内容未通过安全审核，请修改后再试" },
    file_too_large: { message: "头像图片不能超过 2MB" },
    unsupported_media_type: { message: "头像仅支持 PNG、JPG 或 WebP 图片" },
    invalid_image: { message: "图片无法识别或尺寸过大（边长不超过 4096），请换一张" },
    unauthorized: { message: "请先登录" },
    token_expired: { message: "登录已过期，请重新登录" },
    refresh_invalid: { message: "登录已过期，请重新登录" },
  };
  const hit = e.code ? byCode[e.code] : undefined;
  if (hit) {
    // prefer the server's own Chinese detail when it has one
    const msg = /[\u4e00-\u9fff]/.test(e.message) && e.status < 500 ? e.message : hit.message;
    return { field: pick(hit.field), message: e.code === "invalid_credentials" ? hit.message : msg };
  }
  if (e.status === 401) return { message: "用户名或密码错误" };
  return { message: e.message };
}

/* ---------------- safe post-login redirect (no open redirects) ---------------- */
const AUTH_PAGES = /^\/(login|register)(\/|$)/;
/** Reachable without a session even when the server requires one (ZM_AUTH_REQUIRED=1). */

/** Only same-site paths: "/x?y#z". Rejects "//host", "/\host", schemes, control chars, /api and auth pages. */
export function safeNext(raw: string | null | undefined, fallback = "/"): string {
  if (!raw || typeof raw !== "string" || raw.length > 512) return fallback;
  const s = raw.trim();
  if (!s.startsWith("/") || s.startsWith("//") || s.includes("\\")) return fallback;
  if (/[\u0000-\u001f\u007f]/.test(s)) return fallback;
  try {
    const base = "http://zhimeng.invalid";
    const u = new URL(s, base);
    if (u.origin !== base) return fallback;
    if (AUTH_PAGES.test(u.pathname) || u.pathname.startsWith("/api/")) return fallback;
    return u.pathname + u.search + u.hash;
  } catch {
    return fallback;
  }
}

/** Public pages never redirect: 首页, 登录, 注册. */
export const isPublicPath = (path: string) => path === "/" || AUTH_PAGES.test(path);
export const isAuthPage = (path: string) => AUTH_PAGES.test(path);
/**
 * Pages that need a signed-in session:
 * - `/me` always needs a real account when the server requires auth; with ZM_AUTH_REQUIRED=0 it shows the
 *   demo account read-only (editing still needs login).
 * - With `auth_required: true` every page except /, /login and /register needs a session (every world API is 401).
 */
export const needsLogin = (path: string, authRequired: boolean) => !isPublicPath(path) && authRequired;
export const loginHref = (next: string) => `/login?next=${encodeURIComponent(safeNext(next, "/"))}`;
