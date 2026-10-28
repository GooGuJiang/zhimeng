/**
 * Account field rules — the single source for frontend validation and hint text.
 *
 * Agreed with the backend for AUTH-QA-2 (TEAM.md), which tightens contract §4「校验规则」(v1.4-draft2):
 *   - username: starts with a letter, 3–20 chars, letters / digits / underscore only → ^[A-Za-z][A-Za-z0-9_]{2,19}$
 *     (§4 itself only forbids a leading underscore; the backend now also requires a leading letter)
 *   - password: 8–64 chars (§4 says 72; the backend is lowered to 64 to match), letters + digits, not equal to
 *     the username or email, not a common weak password (that last check is server-side: `weak_password`)
 *   - email (optional) ≤254 · nickname 1–20 after trim, no control chars · bio ≤200 · login 1–254  (§4 as written)
 * Reserved usernames (§4, case-insensitive) are checked here too so the user hears it before submitting.
 */
export const USERNAME_RE = /^[A-Za-z][A-Za-z0-9_]{2,19}$/;
export const USERNAME_LEN = { min: 3, max: 20 } as const;
export const RESERVED_USERNAMES = ["demo", "admin", "root", "system", "zhimeng", "api", "null"] as const;

export const PASSWORD_LEN = { min: 8, max: 64 } as const;
export const NICKNAME_LEN = { min: 1, max: 20 } as const;
export const BIO_MAX = 200;
export const EMAIL_MAX = 254;
export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
export const LOGIN_MAX = 254;
/** POST /users/me/avatar (§3.8) */
export const AVATAR_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export const AVATAR_MAX_BYTES = 2 * 1024 * 1024;

/** Hint texts shown under the fields (kept next to the rules so they never drift apart). */
export const HINTS = {
  username: "3–20 位，字母开头，可含数字和下划线；用于登录",
  password: "8–64 位，需同时包含字母和数字",
  nickname: "1–20 个字，显示在顶栏和个人中心",
  email: "可用于登录；不填也可以",
  avatar: "上传 PNG、JPG 或 WebP（不超过 2MB），或选一个预设头像；都不设置时显示昵称首字。",
} as const;
