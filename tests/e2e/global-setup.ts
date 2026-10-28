/**
 * feat/auth：ZM_AUTH_REQUIRED=1 时，原有 AC/演示用例需要登录。这里在所有用例之前注册一个 QA 用户，
 * 把会话 cookie（zm_access Path=/api、zm_refresh Path=/api/auth，域 localhost，与端口无关）写进本次运行专属的状态文件，
 * playwright.config.ts 用它作为默认 storageState —— 浏览器和 `request` 夹具（直连 :8000）都会带上。
 * 默认 ZM_AUTH_REQUIRED=0（匿名 = 演示账号 u_demo）或后端未实现用户系统时写入空状态，行为与以前一致。
 */
import { request, type FullConfig } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// 路径由 playwright.config.ts 按运行生成（ZM_E2E_STATE），避免并发运行互相覆盖
export const STATE = process.env.ZM_E2E_STATE ?? path.join(__dirname, ".auth", "state.json");
const EMPTY = { cookies: [], origins: [] };

export default async function globalSetup(_config: FullConfig) {
  fs.mkdirSync(path.dirname(STATE), { recursive: true });
  const web = process.env.ZM_WEB ?? "http://localhost:3000";
  const ctx = await request.newContext({ baseURL: web });
  try {
    // draft2：未登录 → 401 {code:"unauthorized", auth_required, acting_as}；未实现 → 404
    const me = await ctx.get("/api/auth/me");
    const body = me.status() === 404 ? {} : await me.json().catch(() => ({}));
    const required = (body as { auth_required?: boolean }).auth_required === true;
    if (!required) {
      fs.writeFileSync(STATE, JSON.stringify(EMPTY));
      return;
    }
    const username = `qae2e_${Math.random().toString(16).slice(2, 10)}`;
    const r = await ctx.post("/api/auth/register", {
      data: { username, password: "Zm-QA-pass-2026!", nickname: "QA自动化" },
    });
    if (r.status() !== 201) throw new Error(`global-setup register → ${r.status()} ${(await r.text()).slice(0, 200)}`);
    await ctx.storageState({ path: STATE });
  } finally {
    await ctx.dispose();
  }
}
