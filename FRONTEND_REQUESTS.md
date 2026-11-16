# Frontend requests to backend (from frontend engineer)

Written before API.md existed. If API.md already decides otherwise, API.md wins — I will adapt. Items marked **[need]** matter most.

## 1. Generative UI (F6) — OpenUI Lang  **[need]**
The frontend renders generative UI with OpenUI (`@openuidev/react-lang` `<Renderer>`). Please let the backend return
UI specs as **OpenUI Lang 1.0 program strings**, e.g. a field `ui: { status?: string, relations?: string, inventory?: string, map?: string, knowledge?: string }`
on the world/state payload (or SSE event `ui` with `{panel, program}`).

- The component library is ours (narrative-themed). Its full system prompt (component signatures + rules) is generated to
  `/workspace/zhimeng/frontend/openui/system-prompt.txt` and the JSON spec to `frontend/openui/spec.json`.
  Feed `system-prompt.txt` to the LLM call that produces UI (a "UI Agent" node in LangGraph), or build programs with templates.
- Minimal valid example:
  ```
  root = Col([title, hp])
  title = Title("林晚的状态")
  hp = Meter("体力", 72, 100, "danger")
  ```
- Fallback: if a panel program is missing/invalid, the frontend builds the panel itself from the structured state
  (characters, relations, inventory, locations, stats). So structured state is still required (below).
- Buttons in generated UI emit `@ToAssistant("我要去码头")` → frontend sends it as a free-input action to /play.

## 2. Endpoints — SUPERSEDED
API.md v1 is adopted as-is by the frontend. Section 1 is now a *nice-to-have*: API.md's `UIComponent.openui`
field is exactly where an OpenUI Lang program can go. The frontend renders it if it parses against our library
(`frontend/openui/system-prompt.txt`, regenerate with `pnpm openui:prompt`), otherwise it compiles `props` itself.
Rules for `openui`: program must start with `root = Col(...)`; only components listed in the prompt.

## 3. CORS
Frontend proxies `/api/*` → `http://localhost:8000/api/*` via Next rewrites, so CORS is not required, but allowing
`http://localhost:3000` doesn't hurt. SSE responses: please send `Cache-Control: no-cache` and `X-Accel-Buffering: no`.

## 3. After integration against API v1.1 (frontend, 2026-10-19 15:30)
Frontend is fully wired to v1.1 (all 9 Playwright ACs pass in fallback mode). Remaining asks, most important first:

1. **[need] Opening key scene: also auto-generate narration audio.** After `generate`/`confirm` only the opening *image*
   (`turn_id=null`) exists; API.md says key scenes (opening included) get image **+ audio**. Frontend workaround today:
   if the opening has an image but no audio, it calls `POST /worlds/{id}/assets/tts {text: opening_scene[:600]}` once
   (cache-hit on reload). Please emit both (and `asset` events / rows with `turn_id=null`) so the client needn't.
2. **Regenerate with a tweak.** v1.1 keeps omitted fields, but a short "adjust" note has to be sent as a full `prompt`
   (frontend sends `"<original prompt>（调整：…）"`, reading the original from `state.flags.gen_request.prompt`).
   Suggest an explicit optional `refine: str` field appended server-side, and document `state.flags.gen_request`.
3. **`GET /api/reports` privacy.** It returns every report (content included) to any client. Please scope it
   (per-session/IP or admin token); the frontend only shows a count on the settings page.
4. **Token granularity.** Fallback turn streams send ~8 big `token` chunks; the client smooths them with a typewriter,
   but real-model mode should stream small deltas so first-token latency is visible (SRS: ≤2 s).
5. **UI event_feed / choice_list.** The play page has a dedicated 场外大事件 panel and option buttons, so generative
   `event_feed` and `choice_list` components are not rendered in the side area (avoids duplicates). If you want them
   shown, give them `layout.area="main"` semantics we can agree on.
6. Document `World.opening_options` (present in payloads, not in API.md; frontend uses `GET /options`).
7. Stability note: during my first e2e run the shared :8000 process was restarted mid-turn → proxy 500; the client
   showed 「重试」 and resent the same `client_turn_id` correctly, but please keep :8000 stable while QA runs.

## 4. Accounts (feat/auth, against API v1.4-draft2 + TEAM.md §13) — frontend, 2026-10-28
Frontend is integrated against the real backend in both `ZM_AUTH_REQUIRED=1` (delivery default) and `=0`.
Mock specs, QA `auth.spec.ts` and the full e2e all pass. Remaining asks, most important first:

1. **[need] Honour `tts_enabled=false` server-side.** The pref is only stored (`auth/prefs.py`). When it is off,
   the frontend hides the audio bar, but key-scene narration is still generated, so the user still pays for TTS.
   Please skip the TTS job (and its `asset` event) for worlds whose owner has `tts_enabled=false`.
2. **Preset avatar keys.** `PATCH /users/me {avatar_url:"preset:<key>"}` accepts any `[A-Za-z0-9_-]{1,32}`. The
   frontend offers exactly `moon bamboo boat crane cloud hill lamp ink` (`frontend/src/components/Avatar.tsx`
   `AVATAR_PRESETS`). Please whitelist these keys, or document them in API.md, so other clients render the same set.
3. **Anonymous `GET /auth/me` → 401** shows a red "Failed to load resource" line in the browser console on every
   signed-out page load (the frontend treats it as normal and no longer logs it). Consider `200 {authenticated:false,
   auth_required, acting_as}`, or accept that the 401 is noise.
4. **Copy for `username_taken`.** Backend says 「用户名已被占用」. The frontend shows its own wording
   (「该用户名已被注册，换一个试试，或直接登录」), as QA's spec expects. No change needed unless other clients
   should match.
5. **E2E rate limits.** `ZM_REGISTER_PER_HOUR=10`/IP is used up after one or two full e2e runs (every run registers
   users), and then register returns 429. For CI/QA runs, please document setting `ZM_REGISTER_PER_HOUR` high, or
   exempt loopback when `ZM_ENV=test`.
6. **AUTH-QA-3 (client IP), frontend side done.** `scripts/client-ip-guard.cjs` is preloaded by `pnpm dev`,
   `pnpm start` and the Docker CMD. It drops the client's X-Forwarded-For / X-Real-IP / Forwarded / CF-Connecting-IP / …
   and sends exactly one `X-Forwarded-For: <TCP peer>`. Next's rewrite proxy can't do this itself
   (`base-server` only does `xff ??= socket.remoteAddress`, httpxy forwards headers unchanged), and route handlers
   can't see the socket. Proof: `pnpm test:client-ip` and a real-backend check (6 registrations with different
   spoofed IPs through the proxy hit 429 after `ZM_REGISTER_PER_HOUR=3`). Behind our own reverse proxy (nginx in
   front of the frontend container), set **`ZM_TRUST_PROXY=1` on the frontend**; only then is the upstream's last
   XFF hop used. Please pass it through in docker-compose (`frontend.environment`) when such a proxy is added.
   Keep `ZM_TRUSTED_PROXIES` on the backend limited to the frontend container / loopback.
7. **Origins for non-3000 ports.** Write requests are Origin-checked. Test servers on other ports need
   `ZM_CORS_ORIGINS=http://localhost:<port>,...` (this works without code changes); worth a line in the README.


## 5. Character branch choices & 剧情脉络 (2026-11-16, frontend)
评审意见要「角色分支选择交互演示」。游玩页原先已有选项按钮和自由输入，并排除了 OpenUI `choice_list`
（它会与按钮重复，且不展示后果提示）。前端现已按下面的最小契约实现交互与分支视图；**请后端实现选项提示
与多线回溯**。在接口就绪之前，前端会降级：选项仍显示（缺 `hint` 时用本地短提示补上），脉络按
`GET /turns` 画成只读单线，「另选一条」隐藏。

### 已有、请保持并补齐
- `Option = { id, text, hint? }`，`GET /worlds/{id}/options`，SSE `options` / `done.turn.options`，
  `POST /worlds/{id}/turns { action, option_id, client_turn_id }` 均已对接。
- **[need] 每回合 2–4 个选项，且每个都带简短中文 `hint`（后果提示，建议 ≤24 字）。**
  兜底模式的 `options_for` 目前没有 `hint`，请一并补上，这样 `ZM_FORCE_FALLBACK=1` 录屏也能直接用。

### 新增最小契约
`GET /api/worlds/{id}/branches` →
```json
{
  "current_node_id": "opening | <turn id>",
  "nodes": [{
    "id": "opening | <turn id>",
    "parent_id": "opening | <turn id> | null",
    "turn_id": "<turn id> | null",
    "index": 0,
    "chapter": 1,
    "action": "玩家走到这里时的选择，开局为 null",
    "choice_id": "opt_1 | null",
    "summary": "给脉络看的短旁白，不超过约 40 字",
    "line_id": "line_…",
    "current": false
  }],
  "lines": [{ "id": "line_…", "leaf_id": "<node id>", "current": true }]
}
```
开局节点的 `id` 固定为 `"opening"`（`turn_id` 为 null，`index` 为 0）。`GET /worlds/{id}/turns`
只返回**当前这条线**上的回合（从开局到当前节点），不要把其它线上的回合混进来。

`POST /api/worlds/{id}/branches/rewind`  body: `{ "to_node_id": "opening | <turn id>" }` → 200
```json
{ "current_node_id": "…", "options": [Option], "world": World }
```
把游玩游标回到该节点之后（世界状态、当前选项都恢复到那一步）。**不要删除其它线**——它们继续出现在
`GET /branches` 里。下一次 `POST /turns` 若该节点已经有子节点，则开辟一条新线（分叉）；否则沿当前线继续。
错误：节点不属于本世界时 404 `not_found`（文案用中文，如「找不到要回到的那一步」）。

前端不会在界面上展示 `id` / `line_id` / `option_id` 等技术字段。未实现时请对这两个路径返回 404，
前端即可降级，不必先占位 501。

### 与后端现行实现的对齐（2eb0103 / d7e7eee）
后端已实现上述路径，并做了字段兼容（`current_node_id` / `lines` / `parent_id` /
`summary` / `line_id` / `current` / `choice_id`），另外还有：
- `POST /branches/checkout { turn_id }`（`rewind { to_node_id }` 是别名，`"opening"` 表示开局）
- `GET /branches/path?turn_id=`（只预览、不切换）
- 回溯响应还带 `world` / `turns` / `options` / `taken`
- `Turn.parent_turn_id` / `branch_id`，`World.head_turn_id`；`GET /turns` 只返回当前路径（active=1）
- `Option.hint` 与兜底 `fill_hints`；`TurnRequest.from_turn_id`、可只传 `option_id`

前端已按草案字段读取，能对接这套实现。契约已见 API.md F11。前端没有改后端文件。

### 其它
配音长轮询仍走 `/api/assets/{id}?wait=`，本改动不涉及。录屏演示步骤见 TEAM.md 本节进度。
