# 织梦 Backend API Contract (v1, v1.4-draft2: user accounts)

Base URL: `http://localhost:8000` · all routes prefixed with `/api` · CORS allows `http://localhost:3000` (and 127.0.0.1:3000).
JSON everywhere (UTF-8). Errors: HTTP 4xx/5xx with `{"detail": "...", "code": "..."}` (v1.4-draft: optional `field`, `retry_after`).
**v1.4-draft2 (feat/auth)**: cookie-based login (`zm_access` / `zm_refresh`); send every `fetch` with `credentials: "include"`. See "用户系统接口契约" below.
Static generated assets: `GET /api/static/assets/<file>` (relative `url` fields below start with `/api/static/assets/...`; prefix with base URL or use the Next `/api/*` proxy). `/static/assets/<file>` is kept as a deprecated alias.

Every AI-generated payload carries `"ai_generated": true` and the label `"ai_label": "内容由AI生成"` (F9).

## SSE conventions

Streaming endpoints are `POST` (body JSON) and reply `Content-Type: text/event-stream`.
Use `fetch` + a stream reader (e.g. `@microsoft/fetch-event-source`), not `EventSource` (no POST).
Each message: `event: <name>\ndata: <json>\n\n`. Event names:

| event | data | meaning |
|---|---|---|
| `progress` | `{"stage": str, "message": str, "pct": int 0-100}` | loading / thinking visualisation |
| `token` | `{"text": str}` | incremental narration text (append) |
| `memory` | `{"facts": [Citation]}` | memories retrieved for this turn (F4 transparency) |
| `options` | `{"options": [Option]}` | next choices |
| `event` | `{"events": [WorldEvent]}` | off-screen / world events produced this turn (F3) |
| `ui` | `{"components": [UIComponent]}` | generative-UI specs (F6) |
| `asset` | `Asset` | an illustration / audio became available (F5) |
| `safety` | `SafetyResult` | input/output was blocked or flagged (F9). If `blocked` the stream ends with `done` (no turn is committed) |
| `world` | `World` | full world object (world generation only) |
| `done` | endpoint-specific (see below) | final event; stream closes |
| `error` | `{"message": str, "retryable": bool}` | failure; nothing was committed, progress is safe → retry |

## Core types

```ts
type Mode = "story" | "education"
type Rating = "all" | "teen" | "mature"          // content rating
type Location = { id: string; name: string; description: string; x: number; y: number;   // x,y in 0..100 map coords
                  connections: string[]; interactables: string[] }
type Relation = { target_id: string; type: string; affinity: number /* -100..100 */; note?: string }
type Character = { id: string; name: string; role: string; persona: string; goals: string[];
                   relations: Relation[]; location_id: string | null; mood: string; status: string;
                   is_player: boolean; avatar_emoji?: string }
type Item = { id: string; name: string; description: string; owner_id: string | null; quantity: number }
type KnowledgeCard = { id: string; title: string; content: string; source?: string; turn?: number }
type WorldState = { turn: number; chapter: number; time: string /* in-world time label */; day: number;
                    player_location_id: string | null; flags: Record<string, any>; hp: number; stats: Record<string, number> }
type World = { id: string; title: string; genre: string; tone: string; era: string; setting: string;
               mode: Mode; language: string; premise: string; initial_conflict: string; opening_scene: string;
               player: { name: string; role: string; character_id: string };
               locations: Location[]; characters: Character[]; items: Item[];
               knowledge_cards: KnowledgeCard[];      // education mode (empty otherwise)
               state: WorldState; rating: Rating; minor_mode: boolean; status: "draft"|"active"|"ended";
               created_at: string; updated_at: string; source: "llm" | "fallback";
               opening_options: Option[];             // v1.2 documented: turn-0 options (same as GET /options at turn 0)
               detail_status: "enriching" | "complete" | "local";   // v1.2 two-step generation, see F1
               gen_request: GenerateWorldRequest | null;            // v1.2: original generation request (incl. last `refine`)
               ai_generated: true; ai_label: string }
type WorldSummary = { id; title; genre; tone; mode; turn: number; status; created_at; updated_at }
type Option = { id: string; text: string; hint?: string }
type WorldEvent = { id: string; world_id: string; type: "offscreen"|"world"|"player"|"injected"|"npc_action";
                    summary: string; actor_ids: string[]; location_id: string|null; turn: number; chapter: number;
                    impact: string; timestamp: string /* ISO */; in_world_time: string; seen: boolean }
type Citation = { fact_id: string; content: string; turn: number; chapter: number; kind: string; score: number; source: string /* e.g. "第2章·第5回合" */ }
type Turn = { id: string; world_id: string; index: number; chapter: number; action: string; narration: string;
              options: Option[]; events: WorldEvent[]; facts: string[]; asset_ids: string[]; key_scene: boolean;
              source: "llm" | "fallback";   // v1.2: "fallback" = whole model chain failed, local template narration
              created_at: string; ai_generated: true; ai_label: string }
type Asset = { id: string; world_id: string; type: "image"|"audio"; url: string /* /api/static/assets/<file> */; turn_id: string|null;
               prompt: string; source: "dashscope"|"fallback"; created_at: string;
               status: "pending"|"ready";   // v1.3: pending = placeholder, real file still generating (same id upgrades in place)
               version: number;             // v1.3: +1 on every in-place upgrade / regenerate; url gets ?v=<version> when > 1
               updated_at: string }         // v1.3
type SafetyResult = { allowed: boolean; blocked: boolean; crisis: boolean; categories: string[]; rating: Rating;
                      message: string | null; /* user-facing message, e.g. crisis hotline */ filtered_text?: string }
```

### UIComponent (F6 generative UI)

```ts
type UIComponent = {
  id: string;                     // stable, e.g. "status", "relations", "inventory", "map", "events", "knowledge"
  type: "status_panel" | "relationship_graph" | "inventory" | "map" | "event_feed" | "knowledge_cards" | "choice_list";
  title: string;
  priority: number;               // higher = more prominent; layout hint derived from current plot
  layout: { area: "main" | "side" | "bottom"; size: "sm" | "md" | "lg" };  // v1.2: "bottom" = has a dedicated region (see below)
  props: object;                  // per type, below
  actions: { id: string; label: string; kind: "turn"|"god_inject"|"query"|"navigate"; payload: object }[];
  openui?: string;                // optional OpenUI-lang hint text; frontend may ignore
}
```
props by type:
- `status_panel`: `{ player: {name, role, location: string, hp: number, mood: string}, stats: Record<string,number>, time: string, chapter: number, turn: number, tags: string[] }`
- `relationship_graph`: `{ nodes: [{id, label, role, mood, is_player, emoji}], edges: [{source, target, type, affinity}] }`
- `inventory`: `{ items: [{id, name, description, quantity}] }` (items owned by the player)
- `map`: `{ locations: [{id, name, x, y, description, characters: string[] /*names*/}], edges: [{source,target}], current_location_id }`
- `event_feed`: `{ events: WorldEvent[] }` (latest off-screen events)
- `knowledge_cards`: `{ cards: KnowledgeCard[] }` (education mode only)
- `choice_list`: `{ options: Option[] }`
`layout.area` (v1.2): `main` = narrative-adjacent panels, `side` = side panel, `bottom` = **dedicated areas**. `event_feed` and
`choice_list` are always `area:"bottom"`; they mirror the 场外大事件 panel (`event` stream / `GET /events`) and the option buttons
(`options` event), so a client that already has those dedicated areas may skip them in the side panel (current frontend behaviour).
Action `kind: "turn"` → POST `/api/worlds/{id}/turns` with `payload` as body (`{action}`); `"navigate"` payload `{location_id}` → send as turn action `"前往<地点名>"` (payload contains ready `action` string too).

## Endpoints

### Health
`GET /api/health` → `{ "status": "ok", "llm": bool /* key configured */, "models": {"chat": str, "fast": str, "skeleton": str, "embedding": str, "image": str, "tts": str, "chat_chain": [str], "fast_chain": [str]}, "llm_runtime": {"last_model": str|null, "switches": int, "cooling": [str]}, "version": str }`

### F1 World generation
`POST /api/worlds/generate` (SSE)
Body `GenerateWorldRequest`:
```json
{ "prompt": "一个民国上海滩的侦探故事，我是报社记者", "genre": "悬疑?", "tone": "?", "length": "short|medium|long", "language": "zh",
  "mode": "story", "source_text": null, "minor_mode": false, "rating": "teen", "wait_details": false }
```
Events: `progress` (stages: `safety`,`outline`,`locations`,`characters`,`conflict`,`persist`,`memory`,`done`), `token` (optional raw text while LLM drafts), `world` (World), `safety` (if blocked), `done` `{ "world_id": str, "source": "llm"|"fallback", "detail_status": "enriching"|"complete"|"local" }`, `error`.
**Two-step generation (v1.2).** Step 1: a fast model (`qwen-flash` chain) drafts a skeleton → local rules fill it into a playable world →
`world` (with `detail_status:"enriching"`) → `done` — target preview ≤5 s. Step 2 runs in the background (`qwen-plus` chain) and merges
details **keeping title, ids and names**; then `detail_status` becomes `complete`, or `local` if step 2 failed (skeleton world filled by
local rules, still playable). Client: after `done`, poll `GET /api/worlds/{id}` (e.g. every 2–3 s) while `detail_status==="enriching"`.
`wait_details:true` keeps the SSE open and pushes a second `world` before `done` instead. Without a key / with `ZM_FORCE_FALLBACK=1`
there is one step: `detail_status:"complete"`, `source:"fallback"`.
`POST /api/worlds` (non-streaming, same body) → `World`.
`POST /api/worlds/{id}/regenerate` (SSE, optional body overrides of GenerateWorldRequest) → regenerates the draft in place (same id; same events).
v1.2: body may carry `"refine": "多一点悬疑，主角换成女记者"` — applied **on top of** the original request (`World.gen_request`; server sends
`<original prompt>\n补充要求：<refine>` to the model). The original `prompt` is not modified; `gen_request.refine` stores the latest refine and a
later regenerate without `refine` keeps it; send `"refine": ""` to clear. `World.gen_request` is the formal field
(`state.flags.gen_request` is kept as a deprecated alias with the same content).
`POST /api/worlds/{id}/confirm` → `World` (status → `active`). v1.2: confirm auto-generates the **opening key-scene assets** in the background:
an illustration **and** a narrator audio (`opening_scene`, passed through `check_output` first; not voiced if blocked). Both are stored with
`turn_id=null`; fetch with `GET /api/worlds/{id}/assets` and take the newest `type:"image"` / `type:"audio"` rows with `turn_id===null`
(if step-2 enrichment rewrites the opening after confirm, a new pair is generated). There is no SSE `asset` event for the opening
(confirm is a plain JSON call); poll `/assets` a few times (fallback: ~instant; real: image 10–30 s, audio 3–10 s).
`GET /api/worlds` → `WorldSummary[]` · `GET /api/worlds/{id}` → `World` · `DELETE /api/worlds/{id}` → `{ "ok": true }`
`PATCH /api/worlds/{id}/settings` body `{ "minor_mode"?: bool, "rating"?: Rating }` → `World`

### F2 Play
`POST /api/worlds/{id}/turns` (SSE)
Body: `{ "action": "我去码头找线人", "option_id": "opt_2" | null, "client_turn_id": "uuid?" }`
(`client_turn_id` is an idempotency key: re-sending a committed id returns the committed turn as `done` immediately.)
Events in order: `progress`(stages `safety`,`memory`,`world`,`npc`,`director`,`narrate`,`extract`,`persist`) → `memory` → `event` → `token`* → `options` → `ui` → `asset`* (key scenes) → `done` `{ "turn": Turn, "state": WorldState }`.
Model failure (v1.2, BUG-006): the turn never ends in `error` just because the model chain is down. Fails before the first token →
local template narration (`done.turn.source:"fallback"`). Stream breaks after tokens were sent → the server first resumes by continuation;
if that is exhausted it emits `progress {"stage":"fallback","reset":true,"message":…}` — **clear the narration shown so far** — then streams
the full local-template narration. `done.turn.narration` is always authoritative. `error` remains only for non-model failures (retryable).
`asset` events (v1.3) may appear anywhere **before** `done`: while a turn stream is open, any pending asset of this world (opening,
earlier key scenes, this turn's key scene) that finishes upgrading is pushed again (same `id`, new `url`, `status:"ready"`, higher `version`);
merge by `id`. The stream is not held open after `done` just to wait for upgrades — use `GET /api/assets/{id}?wait=8` for those.
Safety fast path (v1.3): the rule layer (crisis / hard block / injection / rating) still blocks before anything is generated. Suspicious
input gets a background LLM review in parallel with narration; if it flags, the stream stops and the server sends `safety` then
`done {"blocked": true}` — **discard the partial narration**; nothing is committed. After commit, generated narration may be re-reviewed
in the background; if flagged, the stored `Turn.narration` is replaced with a safe text (visible on the next `GET /turns`).
`token` granularity (v1.2): real-model deltas are passed through as they arrive (only the last 8 chars are held back for the safety filter
and flushed at the end); fallback narration is sent in 3-char chunks paced by `STREAM_DELAY`.
On `error` nothing is committed; resend the same body (or use retry below).
`POST /api/worlds/{id}/turns/retry` (SSE, empty body) → regenerates the **last** turn from its pre-turn snapshot (same action), same events.
`GET /api/worlds/{id}/turns?limit=50` → `Turn[]` (ascending)
`GET /api/worlds/{id}/options` → `{ "options": Option[] }` (current options; opening options at turn 0)

### F3 Multi-agent / off-screen events
`GET /api/worlds/{id}/events?type=offscreen&limit=50` → `WorldEvent[]` (newest first)
`POST /api/worlds/{id}/events/seen` body `{ "ids": [str] }` → `{ "ok": true }`

### F4 Memory
`GET /api/worlds/{id}/memory?kind=&limit=100` → `[{ "id", "content", "kind": "fact"|"event"|"summary"|"injected"|"setting", "turn", "chapter", "source", "created_at" }]`
`POST /api/worlds/{id}/memory/query` body `{ "question": "三章前那个线人叫什么？", "top_k": 5 }` → `{ "answer": str, "citations": Citation[], "ai_generated": true, "ai_label": str }`
`GET /api/worlds/{id}/summaries` → `[{ "chapter": int, "from_turn", "to_turn", "summary": str }]`
(A chapter = 5 turns; summary compression runs automatically at chapter end.)

### F5 Multimodal
`GET /api/worlds/{id}/assets` → `Asset[]`
`POST /api/worlds/{id}/assets/illustration` body `{ "turn_id"?: str, "prompt"?: str }` → `Asset` (cached by prompt hash)
`POST /api/worlds/{id}/assets/tts` body `{ "text": str, "voice"?: str, "turn_id"?: str }` → `Asset` (cached)
`POST /api/assets/{asset_id}/regenerate` → `Asset` (new file, bypasses cache)
`GET /api/assets/{asset_id}?wait=<s>` → `Asset` (v1.3). `wait` (0–8 s) long-polls while `status==="pending"` and returns as soon as it is upgraded.
v1.3 deadlines: the illustration / tts / regenerate endpoints answer within ~8 s. If the real file is not ready, they return a placeholder
(`source:"fallback"`, `status:"pending"`); generation continues in the background and upgrades **the same id** (`status:"ready"`,
`source:"dashscope"`, `version+1`, new `url` — new file name plus `?v=version`, so browser caches are bypassed). Refresh signals:
(1) `asset` events inside any open turn stream (see F2), (2) `GET /api/assets/{id}?wait=8`, (3) `GET /worlds/{id}/assets`. `status:"ready"` with
`source:"fallback"` means the real generation failed and the placeholder is final.
Auto: turns flagged `key_scene` (opening, chapter boundary, injected/major events) emit `asset` events for image + audio
(v1.3: waits at most `KEY_SCENE_MEDIA_DEADLINE_S`, default 3 s, then sends placeholders with `status:"pending"`; the same ids upgrade in place later). Fallback: SVG illustration / silent WAV placeholder.

### F6 Generative UI
`GET /api/worlds/{id}/ui?components=status_panel,relationship_graph,inventory,map,event_feed,knowledge_cards` → `{ "components": UIComponent[], "ai_generated": true }`
`POST /api/worlds/{id}/ui/stream` (SSE, body `{ "focus"?: str }`) → `progress`, one `ui` event per component (`{"components":[c]}`), `done {"count": n}`.
Turn streams also emit a full `ui` event.

### F7 God view
`GET /api/worlds/{id}/god/npcs` → `[{ "character": Character, "trajectory": [{ "turn", "location_id", "location_name", "action", "mood", "timestamp" }], "recent_events": WorldEvent[], "memories": [str] }]`
`POST /api/worlds/{id}/god/inject` body `{ "content": "码头突发大火", "target_character_ids"?: [str], "location_id"?: str, "impact"?: "low"|"medium"|"high" }` → `WorldEvent` (stored as event + memory kind `injected`; the director must weave it into the next turns)
`POST /api/worlds/{id}/god/tick` → `{ "events": WorldEvent[] }` (manually run world + all NPC agents once)

### F8 Save / share
`GET /api/worlds/{id}/export` → `SaveFile` = `{ "format": "zhimeng-save", "version": 1, "exported_at", "world": World, "turns": Turn[], "events": WorldEvent[], "memories": [...], "summaries": [...], "trajectories": [...], "ai_label": str }` (download as JSON)
`POST /api/worlds/import` body `SaveFile` → `World` (new id, playable)
`GET /api/worlds/{id}/poster` → `{ "title", "subtitle", "tagline", "summary", "ending": str|null, "characters": [{name, role, emoji}], "stats": {turns, chapters, events}, "image_url": str|null, "theme": {primary, secondary, background}, "qr_text": str, "ai_label": str, "safety_label": str, "rating": Rating }`

### F9 Safety
`POST /api/safety/check` body `{ "text": str, "minor_mode"?: bool }` → `SafetyResult`
`GET /api/safety/policy` → `{ "ratings": [...], "minor_mode": {...}, "crisis_message": str, "ai_label": str }`
`POST /api/reports` body `{ "world_id"?: str, "turn_id"?: str, "content": str, "reason": str }` → `{ "id", "status": "received", "created_at" }`
`GET /api/reports?world_id=<id>` → reports of that world only (v1.2: `world_id` **required**).
`GET /api/reports` without `world_id` (full list) requires header `X-Admin-Token` equal to env `ZM_ADMIN_TOKEN`; if the env var is unset the
full list is disabled → `403 {"detail", "code": "forbidden"}`.
Input blocked → turn/generate stream emits `safety` (blocked=true) then `done {"blocked": true}`; HTTP 200. Crisis content (self-harm etc.) → `safety` with `crisis=true` and `message` containing help hotline.

### F10 Education mode
`POST /api/education/generate` (SSE) body `{ "source_text": "课文/史料原文", "title"?: str, "subject"?: "语文|历史|非遗|...", "grade"?: str, "minor_mode"?: true }` → same events as world generation; World has `mode: "education"` and `knowledge_cards`.
`GET /api/worlds/{id}/education/cards` → `KnowledgeCard[]` (cards unlocked so far, incl. ones produced during turns)
`GET /api/worlds/{id}/education/summary` → `{ "title", "key_points": [str], "cards": KnowledgeCard[], "timeline": [{turn, summary}], "quiz": [{question, options: [str], answer_index: int, explanation}], "reflection": str, "ai_label": str, "source": "llm"|"fallback", "status": "complete"|"pending" }`
v1.2 (BUG-007): responds within ~8 s at most. The LLM version runs in a background job (fast model, short input) and is cached per world + turn.
If it is not ready in time, the response is the local summary with `status:"pending"`; GET again a few seconds later for the LLM version
(`status:"complete"`). All fields of the old shape are always present.

## 用户系统接口契约（feat/auth，草案 v1.4-draft2）

> 状态：**v1.4-draft2**，2026-10-28，后端核心。draft2 按 Grok Bot 的裁定兼容前端和 QA 已经写好的调用方式（§12 列出与 draft1 的差异）。实现在 `feat/auth` 分支。
> 本节在 `TEAM.md` 和 `API.md` 里内容相同；如有出入，以 `API.md` 为准。有异议请写进 `FRONTEND_REQUESTS.md`，或直接找 织梦-后端。

### 0. 设计取舍（为什么这样定）
- **邮箱选填**：注册只要求用户名和密码，邮箱可以不填；填了就必须唯一（不区分大小写）。理由：项目没有邮件服务，做不了邮箱验证和找回密码，强制填邮箱只会增加注册阻力。登录时用户名或邮箱都可以。v1 不做找回密码，演示环境可以由管理员重置。
- **访问别人的资源一律返回 404**（`code:"not_found"`），不返回 403，避免暴露资源是否存在。现有接口找不到世界时本来就返回 404 `世界不存在`，前端不需要新增分支。
- **`ZM_AUTH_REQUIRED` 默认 `0`**（过渡期）：匿名请求按演示账号 `demo` 处理，现有 e2e 和 QA 脚本不用改也能继续跑。上线前改成 `1`。
- **JWT 双 cookie**：access 有效期短、只放在 httpOnly cookie 里，JS 读不到；refresh 有效期长，每次使用都轮换，且只发往 `/api/auth` 路径。前端完全不需要接触 token。
- 密码使用 **argon2id** 哈希（`argon2-cffi`，参数用库默认值）。用户名和邮箱统一转小写后比较唯一性；用户名在 v1 中注册后不能修改。
- 新增依赖：`argon2-cffi`、`PyJWT`、`python-multipart`（multipart 上传要用）、`Pillow`（校验头像并重新编码）。

### 1. 数据模型

**`users` 表**

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | str PK | `u_<12hex>`；演示账号固定为 `u_demo` |
| `username` | str，唯一索引 | 保存原始大小写，唯一性比较用小写（另存 `username_lower` 列并建唯一索引） |
| `email` | str \| null，唯一索引 | 选填；保存时转小写；可以有多个用户为 null |
| `password_hash` | str | argon2id 哈希；**任何接口都不返回** |
| `nickname` | str | 默认等于 username |
| `avatar_url` | str \| null | `/api/static/avatars/<file>` |
| `bio` | str | 默认为空字符串 |
| `preferences` | JSON | 见下方 `Preferences` |
| `is_demo` | bool | 只有 `demo` 账号为 true |
| `token_version` | int | 修改密码时 +1，此前签发的所有 access 和 refresh 一并失效 |
| `created_at` / `updated_at` | datetime（UTC，接口输出 ISO 字符串） | |
| `last_login_at` | datetime \| null | |

**`refresh_tokens` 表**（用于轮换和重放检测）：`jti` PK、`user_id`、`family_id`（同一次登录派生出的一串 token 共用）、`expires_at`、`revoked_at`、`replaced_by`、`created_at`、`user_agent`（截断到 200 字符）。数据库只存 jti，不存 token 原文。

**现有表新增的列**（启动时自动迁移，见 §7）
- `worlds.owner_id`（加索引）和 `worlds.origin`：`"generated"` | `"imported"`，供统计「导入存档」用；旧数据一律记为 `generated`。
- `reports.reporter_id`（可为 null）。
- 回合、事件、记忆、小结、轨迹、角色、资产这些子表**不加列**，归属关系通过 `world_id → worlds.owner_id` 继承，权限检查统一在 `world_or_404` 里做。

```ts
type Preferences = {
  minor_mode: boolean;            // 默认 false。新建世界和教育世界时的默认值，同时是「下限」：开启后请求参数只能更严格（§8）
  rating: Rating;                 // 默认 "teen"。新建世界时分级的上限
  tts_enabled: boolean;           // 默认 true。前端据此决定是否显示和播放配音（后端在关键场景仍会生成音频，v1 不改）
  autoplay_audio: boolean;        // 默认 false
  show_god_view: boolean;         // 默认 true（纯前端偏好，后端只负责存储）
  education: { grade: string | null; subject: string | null; auto_summary: boolean };  // 默认 {null, null, true}；grade/subject 用作 /education/generate 的默认值
  language: "zh";                 // 预留
}
type User = { id: string; username: string; email: string | null; nickname: string; avatar_url: string | null; bio: string;
              preferences: Preferences; is_demo: boolean; created_at: string; updated_at: string; last_login_at: string | null }
```
`World`、`WorldSummary` 新增只读字段 `owner_id: string`。`World` 另新增 `origin: "generated" | "imported"`。

### 2. 认证方式
- **Cookie**（均为 `HttpOnly; SameSite=Lax`，`Secure` 由 `ZM_COOKIE_SECURE` 控制，默认 0，开发环境用 http 也能工作，上线 https 时设为 1）：
  - `zm_access`：JWT（HS256），`Path=/api`，有效期 `ZM_ACCESS_TTL_MIN`（默认 30 分钟）。claims：`sub`=user_id、`typ`="access"、`ver`=token_version、`iat`、`exp`。
  - `zm_refresh`：JWT（HS256），`Path=/api/auth`，有效期 `ZM_REFRESH_TTL_DAYS`（默认 30 天；登录时 `remember:false` 则签成会话 cookie，服务端只认 1 天）。claims：`sub`、`typ`="refresh"、`jti`、`fam`、`ver`、`exp`。
  - **轮换**：每次调用 `POST /api/auth/refresh` 都作废旧 jti 并签发新的 access 和 refresh。如果收到一个**已作废**的 refresh，视为被盗用重放，整串 family 全部吊销，返回 401 `refresh_invalid`。
- **密钥**：读取 `ZM_JWT_SECRET`。没有设置时，第一次启动随机生成 64 字节，写入 `$ZM_DATA_DIR/jwt_secret`（权限 0600），之后重启沿用这个文件。密钥不写日志，也不出现在 `/api/health`。
- **前端调用**：所有 `fetch`（包括 SSE 的 fetch-event-source）都要加 `credentials: "include"`。走 Next 同源代理 `/api/*` 时浏览器默认就会带上 cookie，但为了兼容 `NEXT_PUBLIC_API_BASE` 直连后端的模式，统一加上。
- **CORS**：`allow_credentials=True`，`allow_origins` 必须写明确的来源（`ZM_CORS_ORIGINS` / `cors_origins`，默认 `http://localhost:3000,http://127.0.0.1:3000`），不能用 `*`。这些现在已经满足。注意 `localhost` 和 `127.0.0.1` 属于不同 site，cookie 不互通，开发时请统一用一个。
- **CSRF**：靠 `SameSite=Lax` 防跨站提交；另外所有写接口只接受 `application/json`（头像上传除外，它是 multipart，但同样受 Lax 保护），并校验 `Origin` 头：只要请求带了 Origin，就必须在 CORS 白名单内，否则返回 403 `forbidden`。
- **SSE 鉴权**：SSE 接口都是 `POST + fetch`，和普通接口一样靠 cookie 鉴权，**不需要**在 URL 里带 token。鉴权在建立流之前完成：失败时直接返回 HTTP 401/404 JSON，不会先返回 200 再在流里报错。流开始后如果 access 过期，不会中断这条流。
- **静态文件**：`/api/static/assets/*` 和 `/api/static/avatars/*` 不鉴权，文件名本身是不可猜测的随机 id，以便 `<img>`/`<audio>` 直接引用。

### 3. 接口

统一错误格式沿用现有风格：`{"detail": "给用户看的中文", "code": "<机器码>"}`，可以附带 `field`（出错的字段名）和 `retry_after`（秒）。

#### 3.1 `POST /api/auth/register`（公开）
```json
// 请求
{ "username": "lin_xiaoyu", "password": "Dream2026!", "email": "lin@example.com", "nickname": "林小雨" }
// 201 → 注册成功后自动登录（Set-Cookie: zm_access, zm_refresh）
{ "user": User }
```
错误：422 `validation_error`（附 `field`，比如 `{"detail":"用户名只能包含字母、数字、下划线，长 3–20 位","code":"validation_error","field":"username"}`）· 400 `weak_password` · 409 `username_taken` · 409 `email_taken` · 400 `username_reserved` · 429 `rate_limited`。

#### 3.2 `POST /api/auth/login`（公开）
```json
{ "login": "lin_xiaoyu", "password": "Dream2026!", "remember": true }   // login 可以填用户名或邮箱（含 @ 就按邮箱匹配），不区分大小写
// 200 + Set-Cookie
{ "user": User }
```
错误：401 `invalid_credentials`，detail 固定为「用户名或密码错误」，不区分是用户不存在还是密码错 · 429 `rate_limited`（见 §5）· 422 `validation_error`。

#### 3.3 `POST /api/auth/logout`（公开，幂等）
请求体为空。返回 **204**（无 body），清除两个 cookie，并吊销当前 refresh 所在的 family；同一账号其他设备的会话不受影响。没有登录时调用也返回 204。

#### 3.4 `POST /api/auth/refresh`（公开，需要 `zm_refresh` cookie）
请求体为空。返回 200 `{"user": User}` 并 Set-Cookie 新的两个 cookie。
错误：401 `refresh_invalid`（缺失、过期、已作废、被重放、或修改密码后 `ver` 不匹配），同时清除 cookie。

#### 3.5 `GET /api/auth/me`（公开）
```json
// 已登录 → 200
{ "authenticated": true, "user": User, "auth_required": false }
// 未登录 → 401（前端按 401 判定未登录）。ZM_AUTH_REQUIRED=0 时 acting_as 为 demo，表示匿名请求的数据都记在 demo 名下，前端据此显示「演示账号」提示
{ "detail": "请先登录", "code": "unauthorized", "auth_required": false,
  "acting_as": { "id": "u_demo", "username": "demo", "nickname": "演示账号" } }
// ZM_AUTH_REQUIRED=1 且未登录 → 401
{ "detail": "请先登录", "code": "unauthorized", "auth_required": true, "acting_as": null }
```
带了 `zm_access` 但已过期或无效时返回 401 `token_expired`，同样附 `auth_required` / `acting_as`，前端据此去调 refresh。
`/auth/me` 只认合法的 `zm_access`：任何伪造、篡改、签名不对、或用了未知名字的 cookie（例如 `zm_session`）都**不能**通过鉴权。

#### 3.6 `PATCH /api/users/me`（需登录；`PATCH /api/auth/me` 是它的别名，行为完全相同）
```json
{ "nickname": "小雨", "bio": "喜欢民国悬疑", "email": "new@example.com", "current_password": "Dream2026!" }
// 字段都可选；email 传 null 表示删除。修改或删除 email 必须同时带 current_password
// 200
{ "user": User }
```
错误：401 `unauthorized` / `token_expired` · 422 `validation_error` · 409 `email_taken` · 401 `wrong_password`（修改邮箱时 current_password 错误）· 403 `demo_readonly`（demo 账号不能改资料、密码、头像和邮箱，偏好可以改）。

#### 3.7 `POST` 或 `PUT /api/users/me/password`（需登录，两种方法等价）
```json
{ "current_password": "Dream2026!", "new_password": "Weave#Dream88" }
// 204（无 body）→ token_version+1：其它设备全部下线，本设备重新签发 cookie
```
错误：401 `wrong_password` · 400 `weak_password` · 400 `same_password` · 403 `demo_readonly` · 429 `rate_limited`（连续 5 次输错当前密码，锁 5 分钟）。

#### 3.8 `POST /api/users/me/avatar`（需登录，`multipart/form-data`，字段名 `file`）
- 只接受 `image/png`、`image/jpeg`、`image/webp`，按文件头判断真实类型，不信任扩展名和 Content-Type。大小不超过 **2 MB**，边长不超过 4096。
- 服务端居中裁成正方形，缩放到 256×256，重新编码为 webp（同时去掉 EXIF），存为 `$ZM_DATA_DIR/avatars/<user_id>_<rand>.webp`，旧文件删除。
```json
// 200
{ "avatar_url": "/api/static/avatars/u_3f2a9c1b7d4e_8k2j.webp", "user": User }
```
错误：413 `file_too_large` · 415 `unsupported_media_type` · 400 `invalid_image`（文件损坏或超过 4096 边长）· 403 `demo_readonly`。
`DELETE /api/users/me/avatar` → 200 `{ "avatar_url": null, "user": User }`。没有头像时，前端用 nickname 首字显示默认头像。

#### 3.9 偏好 `GET` / `PUT` / `PATCH /api/users/me/preferences`（需登录；`ZM_AUTH_REQUIRED=0` 时匿名请求读写 demo 的偏好）
```json
// GET 200
{ "preferences": Preferences }
// PUT：整体覆盖，没传的字段回到默认值（见 §1）
{ "minor_mode": false, "rating": "teen", "tts_enabled": true, "autoplay_audio": false, "show_god_view": true,
  "education": { "grade": null, "subject": null, "auto_summary": true }, "language": "zh" }
// PATCH：部分合并（education 也是部分合并）
{ "minor_mode": true, "tts_enabled": false, "education": { "grade": "初二" } }
// 两者都返回 200
{ "preferences": Preferences }
```
请求体也可以包一层 `{"preferences": {...}}`，效果相同。
不论 PUT 还是 PATCH，只要让未成年人模式从 **true 变为 false**，都必须同时带 `"current_password"`，作为家长确认（PUT 漏传 minor_mode 时回到默认值 false，也算关闭）。没带或密码错误返回 401 `wrong_password`；demo 账号不能关闭，返回 403 `demo_readonly`。打开（变严格）不需要密码。
错误：422 `validation_error`（未知字段或取值非法）。

#### 3.10 `GET /api/users/me/stats`（需登录；`ZM_AUTH_REQUIRED=0` 时匿名请求统计 demo 的数据）
只读，只查本地数据库，**不调用大模型**，目标响应时间 <200 ms。
```json
{
  "worlds":   { "total": 7, "story": 5, "education": 2, "draft": 1, "active": 5, "ended": 1, "imported": 1 },
  "saves":    { "slots": 6, "imported": 1 },
  "play":     { "turns": 86, "chapters": 19, "injected_events": 4, "offscreen_events": 51, "memories": 233,
                "first_played_at": "2026-10-19T08:12:00+00:00", "last_played_at": "2026-10-28T07:40:11+00:00" },
  "assets":   { "image": 14, "audio": 15 },
  "learning": { "worlds": 2, "turns": 23, "knowledge_cards": 17, "summaries": 1,
                "latest": LearningRecord | null },
  "reports_submitted": 0,
  "recent_worlds": [ WorldSummary ]
}
```
字段来源，全部能从现有数据算出来：
- `worlds.*`：按 `worlds.mode`、`status`、`origin` 计数。
- `saves.slots`：非草稿世界的数量。每个世界都会自动存档，可以继续玩，即「存档位」。`saves.imported`：通过 `/worlds/import` 导入的数量。导出是浏览器下载，不计数。
- `play.turns`：`turns` 表计数。`play.chapters`：各世界 `state.chapter` 之和。`injected_events` / `offscreen_events`：`events.type` 为 `injected` / `offscreen` 的计数。`memories`：`memories` 表计数。`first_played_at` / `last_played_at`：最早和最近一个回合的 `created_at`。
- `assets.*`：`assets.type` 计数。
- `learning.worlds`：`mode=education` 的世界数。`learning.turns`：这些世界的回合数。`learning.knowledge_cards`：这些世界的 `knowledge_cards` 数量之和。
- `learning.summaries`：已持久化学习小结的教育世界数。`learning.latest`：最近更新的那一条学习记录，没有教育世界时为 null；完整列表见 §3.11。
- `LearningRecord.summary`：**最近一次已生成的学习小结**。`GET /education/summary` 每次得到 `status:"complete"` 的结果，都会持久化到 `state.flags.edu_summary`。从没生成过时为 `null`，前端可以显示「生成学习小结」按钮，点击后去调 `/education/summary`。

#### 3.11 `GET /api/users/me/learning?limit=20&offset=0`（需登录；模式 0 下匿名请求对应 demo）
学习记录，即教育模式的世界，按 `updated_at` 倒序分页。`limit` 取 1–100，默认 20。
```ts
type LearningRecord = { world_id: string; title: string; subject: string | null; grade: string | null; status: string;
  turns: number; cards: number; created_at: string; updated_at: string;
  summary: { key_points: string[]; reflection: string; source: "llm" | "fallback"; turn_count: number; generated_at: string } | null }
```
```json
// 200
{ "items": [ LearningRecord ], "total": 2, "limit": 20, "offset": 0 }
```
- `recent_worlds`：最近更新的 5 个世界。

### 4. 校验规则
| 字段 | 规则 | 错误码 |
|---|---|---|
| username | 3–20 位，`^[A-Za-z0-9_]+$`，不能以下划线开头；保留名（不区分大小写）：`demo admin root system zhimeng api null` | `validation_error` / `username_reserved` |
| password | 8–72 位；至少包含字母和数字两类字符；不能等于用户名或邮箱；不能是常见弱密码（内置 top-100 列表） | `weak_password`（detail 写明原因） |
| email | 选填；不超过 254 位；简单格式校验 `^[^@\s]+@[^@\s]+\.[^@\s]+$`；保存时转小写 | `validation_error` |
| nickname | 去掉首尾空白后 1–20 个字符（中文算 1 个），不能包含控制字符；需要过 `safety.check_input(context="world_prompt")` 的规则层 | `validation_error` / `content_blocked` |
| bio | 0–200 个字符；同样过规则层审核 | `validation_error` / `content_blocked` |
| login | 1–254 位 | `validation_error` |

`content_blocked` 为 400，detail 使用安全模块返回的 message。

### 5. 限流（单进程内存实现，重启后清零）
- **登录**：同一 IP 加同一 login（转小写），15 分钟内失败 5 次，锁 5 分钟。另外同一 IP 15 分钟内失败 20 次（不管用哪个 login），锁 15 分钟。登录成功会清零该 IP+login 的计数。
- **注册**：同一 IP 每小时最多 10 次。
- **修改密码**：同一用户输错当前密码 5 次，锁 5 分钟。
- **refresh**：同一 IP 每分钟 60 次。
- 被限流时返回 HTTP 429，带响应头 `Retry-After: <秒>`，响应体为 `{"detail":"尝试次数过多，请 4 分 32 秒后再试","code":"rate_limited","retry_after":272}`。锁定期内即使密码正确也返回 429。
- IP 取连接的对端地址。只有对端是 `127.0.0.1` 或 `::1`（即 Next 代理）时，才采信 `X-Forwarded-For` 的第一段；`ZM_TRUST_PROXY=0` 可以关闭这项采信。

### 6. 数据归属与权限
- **归属**：`worlds.owner_id` 决定世界及其所有子数据（回合、事件、记忆、小结、轨迹、角色、资产、海报、导出）归谁。创建、生成、教育生成、导入时，`owner_id` 记为当前用户（`ZM_AUTH_REQUIRED=0` 下的匿名请求记为 `u_demo`）。导入存档时，存档里的 `owner_id` 一律忽略，记为导入者。
- **当前身份的确定**（依赖 `current_user`）：
  1. 有合法的 `zm_access` → 该用户。
  2. 有 `zm_access` 但已过期或无效 → **401 `token_expired`**，两种模式都一样。已登录用户不会被悄悄当成 demo。
  3. 没有 access cookie：`ZM_AUTH_REQUIRED=1` → **401 `unauthorized`**（`{"detail":"请先登录","code":"unauthorized"}`）；`ZM_AUTH_REQUIRED=0`（**默认**）→ demo 用户。
- **访问别人的世界或资产**：返回 **404 `not_found`**（`世界不存在` / `资源不存在`）。`GET /api/worlds` 只列出自己的世界。
- **需要鉴权的接口**（按上面的规则确定身份，并检查归属）：
  - `/api/worlds` 下的所有接口：generate、`POST /worlds`、regenerate、confirm、列表、详情、删除、settings、turns、retry、options、events、events/seen、memory、memory/query、summaries、assets、illustration、tts、ui、ui/stream、god/npcs、god/inject、god/tick、export、import、poster、education/cards、education/summary。
  - `/api/assets/{id}`、`/api/assets/{id}/regenerate`（通过 asset 所属的 world 检查归属）。
  - `POST /api/education/generate`。
  - `POST /api/reports`（记录 `reporter_id`；如果带了 world_id，该世界必须属于自己）；`GET /api/reports?world_id=`（只能查自己的世界；管理员用 `X-Admin-Token` 查全量的逻辑不变）。
  - `/api/users/me/*`。PATCH 资料（含 `PATCH /api/auth/me`）、密码、头像这几个接口**始终要求真实登录**：即使 `ZM_AUTH_REQUIRED=0`，匿名请求也返回 401 `unauthorized`。preferences 和 stats 在模式 0 下匿名请求作用于 demo。
- **公开接口**：`/api/health`（新增 `"auth": {"required": bool}`）、`/api/safety/policy`、`/api/safety/check`、`/api/auth/register|login|logout|refresh`、`GET /api/auth/me`（未登录时返回 401，见 §3.5）、静态文件。
- **调试接口** `GET /api/debug/status`：需要真实登录，或带与 `ZM_ADMIN_TOKEN` 一致的 `X-Admin-Token` 头；否则返回 401 `unauthorized`。返回 `{auth_required, multimodal: <multimodal.status()> | null, llm_runtime}`，不发起远程调用，不影响 `/api/health`。
- 后台任务（补全、资产升级、重启后恢复补全）不涉及用户身份，按 world_id 工作，行为不变。

### 7. 旧数据迁移（启动时自动执行，幂等）
1. `create_all` 新建 `users` 和 `refresh_tokens` 表；沿用 `_MIGRATIONS` 机制给已有表加列：`worlds.owner_id VARCHAR`、`worlds.origin VARCHAR DEFAULT 'generated'`、`reports.reporter_id VARCHAR`，并建 `owner_id` 索引。
2. 如果还没有 demo 账号，就创建：`id=u_demo, username=demo, nickname=演示账号, is_demo=true`。密码优先读 `ZM_DEMO_PASSWORD`；没设置时随机生成 20 位，写入 `$ZM_DATA_DIR/demo_password.txt`（权限 0600）。**密码不打印到日志**，日志里只写文件路径。之后修改 `ZM_DEMO_PASSWORD` 会在下次启动时更新 demo 的哈希。
3. `UPDATE worlds SET owner_id='u_demo' WHERE owner_id IS NULL`：旧世界全部归 demo。`World.data` JSON 里的 `owner_id` 不作为权威来源，以列为准，输出时从列注入。
4. 测试和 QA 用的 tmp `ZM_DATA_DIR` 同样会自动生成 demo、密码文件和 jwt_secret。

### 8. 未成年人模式与偏好的关系（**偏好是默认值，请求参数只能更严格**）
- 生成世界、教育生成、导入时：有效 `minor_mode` = `请求.minor_mode` **或** `偏好.minor_mode`。有效 `rating` = min(`请求.rating`（缺省时取偏好的 rating）, `偏好.rating`)，`minor_mode` 为 true 时再封顶到 `ZM_MINOR_MAX_RATING`（默认 teen）。分级从低到高为 all < teen < mature。
- 请求里没有传 `minor_mode` 字段时，取偏好的值。现有的请求默认值不变：`GenerateWorldRequest.minor_mode=false`，`EducationGenerateRequest.minor_mode=true`。
- `PATCH /api/worlds/{id}/settings`：偏好开启未成年人模式时，`minor_mode:false` 会被**忽略**，并且 rating 不能超过上限。返回的 `World` 是实际生效的值，响应头带 `X-ZM-Clamped: minor_mode,rating`，前端可以提示「已按账号的未成年人模式设置」。
- 世界生成之后，偏好再变更不会回溯改动已有世界（世界自己的 `minor_mode` 字段仍是安全模块的输入）。但偏好开启时，打开该用户的世界会按上面的规则在读取时收紧：`GET /worlds/{id}` 返回收紧后的 `minor_mode` 和 `rating`，回合和生成同样按收紧后的值审核；收紧后的值在该世界下一次保存时写回数据库。
- 偏好里的 `education.grade` / `subject` 是 `/education/generate` 对应字段的默认值。

### 9. 错误码一览（新增部分；HTTP 状态码 → code）
| HTTP | code | 场景 |
|---|---|---|
| 401 | `unauthorized` | 没有登录凭证（需要登录的场景） |
| 401 | `token_expired` | access 过期或无效 → 前端调用 refresh 后重试一次 |
| 401 | `refresh_invalid` | refresh 失效 → 前端清除登录态，跳转登录页或回到匿名模式 |
| 401 | `invalid_credentials` | 登录时用户名或密码错误 |
| 401 | `wrong_password` | 修改密码、邮箱、关闭未成年人模式时，当前密码错误 |
| 400 | `weak_password` / `same_password` / `username_reserved` / `invalid_image` / `content_blocked` | |
| 403 | `forbidden` / `demo_readonly` | Origin 不在白名单 / demo 账号不能执行此修改 |
| 404 | `not_found` | 资源不存在，或不属于当前用户 |
| 409 | `username_taken` / `email_taken` | |
| 413 | `file_too_large` | 头像超过 2 MB |
| 415 | `unsupported_media_type` | 头像类型不支持 |
| 422 | `validation_error` | 字段校验失败（附 `field`） |
| 429 | `rate_limited` | 附 `retry_after` 和 `Retry-After` 头 |
所有 detail 都是给用户看的中文（前端 `friendlyMessage` 对 4xx 直接显示 detail）。

### 10. 新增环境变量
`ZM_AUTH_REQUIRED`（默认 0）· `ZM_JWT_SECRET`（缺省时自动生成并保存到 `$ZM_DATA_DIR/jwt_secret`）· `ZM_ACCESS_TTL_MIN`（30）· `ZM_REFRESH_TTL_DAYS`（30）· `ZM_COOKIE_SECURE`（0）· `ZM_DEMO_PASSWORD`（缺省时随机生成并写入 `$ZM_DATA_DIR/demo_password.txt`）· `ZM_TRUST_PROXY`（1，只采信来自本机代理的 XFF）· `ZM_AVATAR_MAX_BYTES`（2097152）。

### 11. 前端对接清单（织梦-前端）
0. draft2 改动：`register` / `login` 返回 `{user}`，需要取 `.user`；`logout` 和改密码返回 204；未登录时 `/auth/me` 返回 401，但 401 的 body 里有 `auth_required` 和 `acting_as`。
1. `lib/api.ts` 和 `lib/sse.ts`：所有请求加 `credentials:"include"`。统一包一层：收到 401 `token_expired` 时先 `POST /api/auth/refresh`（并发请求共享同一个 refresh promise），然后重试**一次**；refresh 返回 `refresh_invalid` 就清除登录态。SSE 在建立前也可能收到 401，同样处理。
2. 新增页面：`/login`、`/register`（用户名、密码、可选邮箱、昵称；按 `field` 把错误显示到对应字段下；429 时按 `retry_after` 倒计时）、`/me` 个人中心（资料编辑、头像上传带裁剪预览、修改密码、偏好设置、统计面板、最近世界、学习记录）。
3. 全局：启动时调 `GET /api/auth/me`，顶栏显示头像和昵称或「登录」按钮；`auth_required:true` 且未登录时，访问受保护页面跳转 `/login?next=`；`auth_required:false` 且未登录时，显示提示条「当前为演示账号，登录后保存到你自己的账号」。
4. 世界或资产返回 404 时，沿用现有的「找不到对应的内容」提示（别人的世界也是 404）。
5. 生成表单和教育表单里 `minor_mode`、`rating`、`grade`、`subject` 的默认值改为读用户偏好；偏好开启未成年人模式时，世界设置页里「关闭未成年人模式」的开关置灰。看到 `X-ZM-Clamped` 响应头时给出提示。
6. 配音：`preferences.tts_enabled=false` 时隐藏或不播放音频，`autoplay_audio` 控制是否自动播放。
7. 登出后清空本地缓存（世界列表、待重试的回合请求体等）。
8. 建议新增 data-testid（交给 QA 写进 `tests/e2e/TESTIDS.md`）：`auth-username`、`auth-password`、`auth-email`、`auth-submit`、`auth-error`、`user-menu`、`logout-btn`、`profile-nickname`、`profile-bio`、`avatar-upload`、`pref-minor-mode`、`stats-panel`。

### 12. draft2 相对 draft1 的变更（Grok Bot 裁定，2026-10-28）
1. `GET /api/auth/me` 未登录时改为返回 401 `{detail, code:"unauthorized", auth_required, acting_as}`；已登录时返回 200 `{authenticated:true, user, auth_required}`。
2. register 和 login 返回 `{user}`（不变，前端需要改）。
3. logout 和改密码成功都返回 **204**。
4. 改密码同时接受 POST 和 PUT；`invalid_password` 合并为 `wrong_password`。
5. 偏好同时支持 PUT（整体覆盖，缺的字段回到默认值）和 PATCH（部分合并）。
6. 新增 `GET /api/users/me/learning`（分页）；`stats.learning` 只保留计数和 `latest`。
7. 新增 `PATCH /api/auth/me`，作为 `PATCH /api/users/me` 的别名。
8. cookie 名仍是 `zm_access` / `zm_refresh`；任何无效或伪造的 cookie（包括 `zm_session`）都不能通过鉴权。
9. 新增 `GET /api/debug/status`；TEAM.md 新增「账号/鉴权 QA 契约」一节。

## Changelog

### v1.1 (2026-10-19, backend core) — all changes are additive except the static path
- **Static path**: generated assets are served at `/api/static/assets/<file>`; every `url` / `image_url` field starts with `/api/static/assets/`. `/static/assets/<file>` remains as a deprecated alias (BUG-004).
- `GET /api/health` also returns `"fallback": bool` (true = local templates, no remote calls).
- `progress` data also carries `"percent"` (same value as `pct`).
- Turn `done` for an already-committed `client_turn_id` carries `"idempotent": true`.
- Turn streams may emit a non-blocking `safety` event (e.g. `crisis=true` hint, or output masked/replaced) before `done`; when the narration was replaced, `done.turn.narration` is authoritative (streamed tokens may differ — render `done.turn.narration` at the end).
- `UIComponent` also carries `ai_generated: true`, `ai_label`; `openui` is always present (OpenUI Lang 1.0, first line `root = Col([...])`, components from `frontend/openui/system-prompt.txt`). `GET /ui` accepts optional `focus=<type|id>` (that component gets priority 100).
- `SaveFile` also has `turn_snapshots` (per-turn pre-turn snapshot so imported saves can `retry`), `assets`, `ai_generated`. Import accepts saves without them.
- `POST /api/reports` response may include `"priority": "high"|"normal"`.
- `POST /api/worlds/{id}/god/inject` returns HTTP 400 `{detail, code:"bad_request"}` when the content is blocked by safety; `POST /worlds/import` 400 for an invalid save.
- `POST /api/worlds/{id}/assets/tts` returns 400 if the text fails `check_output`.
- `regenerate` body: any `GenerateWorldRequest` field; omitted fields keep the original request.

### v1.2 (2026-10-19, backend core) — additive except `GET /api/reports` scoping
- F1 two-step world generation: `World.detail_status`, `GenerateWorldRequest.wait_details`, `done.detail_status`, progress stage `done`;
  poll `GET /api/worlds/{id}` while `enriching`. Education generate supports `wait_details` too.
- LLM model fallback chain on 429 / rate limit / disconnect / unknown model (configurable in `config.py` / env:
  `CHAT_MODEL_CHAIN`, `FAST_MODEL_CHAIN`, `SKELETON_MODEL_CHAIN`, `SKELETON_MODEL`, `MODEL_COOLDOWN_S`); local templates only when the whole chain fails.
  `GET /api/health` adds `models.skeleton/chat_chain/fast_chain` and `llm_runtime`.
- Retrying the last turn keeps god-view manual tick events; the retried narration still sees them.
- Opening key scene: image **and** narrator audio auto-generated on confirm (`turn_id=null` assets).
- Regenerate `refine` field; `World.gen_request` documented as a formal field (`state.flags.gen_request` = deprecated alias).
- `GET /api/reports` requires `world_id`; full list only with `X-Admin-Token` == `ZM_ADMIN_TOKEN` (disabled when unset). **Breaking** for
  callers that listed all reports without `world_id`.
- Fine-grained `token` deltas (see F2); a real-model narration stream that breaks mid-way is resumed by continuation instead of failing.
- BUG-006: model failures degrade to local templates (`Turn.source`, `progress.stage="fallback"` + `reset:true`); NPC / world agents / memory Q&A /
  chapter summaries / extraction also fall back locally.
- BUG-007: non-streaming LLM calls have a total time limit (`SYNC_LLM_TIMEOUT_S`, default 8 s) and fall back locally; safety checks are capped at
  `GUARD_TIMEOUT_S` (6 s) and then use the rules-only layer; `/education/summary` adds `status`/`source` (async LLM version).
- `layout.area` semantics for `event_feed` / `choice_list` (dedicated areas); `World.opening_options` documented.

### v1.3 (2026-10-19, backend core) — additive
- `Asset.status` (`pending`|`ready`), `Asset.version`, `Asset.updated_at`; upgraded urls change (new file + `?v=version`).
- `GET /api/assets/{id}` (+ `?wait=` long-poll, max 8 s).
- Illustration / tts / regenerate endpoints use an 8 s deadline (placeholder + background in-place upgrade); key-scene media waits ≤`KEY_SCENE_MEDIA_DEADLINE_S` (default 3 s);
  opening image/audio placeholders appear ~1 s after confirm and upgrade in place.
- Upgrade signal inside open turn streams: `asset` event with the same id, `status:"ready"` (also for this turn's key-scene assets).
- Turn input safety fast path (`safety` + `done{blocked:true}` may now arrive after some `token`s); post-commit narration review.
- Graceful shutdown waits ≤10 s for background asset upgrades.

### v1.4-draft（2026-10-28，后端核心，`feat/auth` 分支）：用户系统。仅为契约，尚未实现
- 新增 `/api/auth/register|login|logout|refresh|me`，以及 `/api/users/me`（PATCH）、`/api/users/me/password`（PUT）、`/api/users/me/avatar`（POST/DELETE）、`/api/users/me/preferences`（GET/PATCH）、`/api/users/me/stats`（GET）。
- 认证使用 httpOnly cookie `zm_access`（Path=/api，30 分钟）和 `zm_refresh`（Path=/api/auth，30 天，轮换并检测重放），SameSite=Lax；前端所有请求需加 `credentials:"include"`。
- 数据归属：`worlds.owner_id`（子数据通过 world 继承）、`worlds.origin`、`reports.reporter_id`；`World` / `WorldSummary` 新增 `owner_id`，`World` 新增 `origin`。访问别人的资源返回 404。`GET /api/worlds` 只列出自己的世界。
- `ZM_AUTH_REQUIRED` 默认为 0，匿名请求按 demo 账号处理，对现有调用方无破坏；设为 1 时匿名访问受保护接口返回 401 `unauthorized`。过期 access 在两种模式下都返回 401 `token_expired`。
- 启动时自动迁移，旧数据归 demo（`u_demo`）；demo 密码来自 `ZM_DEMO_PASSWORD`，未设置时生成并写入 `$ZM_DATA_DIR/demo_password.txt`，不打印到日志。
- 用户偏好中的 `minor_mode` / `rating` 作为默认值和下限，请求参数只能更严格；世界 settings 被收紧时，响应头带 `X-ZM-Clamped`。
- `/api/health` 新增 `auth.required`。新增错误码见上文 §9。

### v1.4-draft2（2026-10-28，后端核心）：按裁定兼容前端和 QA
- 未登录时 `GET /api/auth/me` 返回 401 `{detail, code:"unauthorized", auth_required, acting_as}`；logout 和改密码返回 204；改密码同时接受 POST 和 PUT，旧密码错误的错误码为 `wrong_password`。
- 偏好同时支持 PUT（整体覆盖）和 PATCH（部分合并）；新增 `GET /api/users/me/learning`（分页），`stats.learning` 改为只含计数和 `latest`。
- 新增 `PATCH /api/auth/me`（别名）和 `GET /api/debug/status`（需要登录或 X-Admin-Token）。
