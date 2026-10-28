# 织梦 — Team coordination

| Owner | Area | Paths |
|---|---|---|
| Backend core | F1-F4, F6-F8, F10, LangGraph, memory, routes, DB | `backend/app/{agents,graph,memory,routes,services,ui,llm}`, `backend/app/{main,config,db,schemas}.py`, `API.md` |
| Frontend | Next.js + OpenUI | `frontend/` |
| Safety & multimodal | F5, F9 internals | `backend/app/safety/service.py`, `backend/app/multimodal/service.py` (+ new modules inside those packages) |
| QA / integration | tests, README, dev script, docs | `backend/tests/integration/` (API pytest smoke), `tests/e2e/` (Playwright), `scripts/`, `README.md`, `docs/`, `BUGS.md`, `.env.example`, root `.gitignore` |

API contract for the frontend: `/API.md` (backend core keeps it current). Frontend asks go to `FRONTEND_REQUESTS.md`.

## Backend internal interfaces (stable — change only by agreement here)

Callers (routes, `app/graph/turn_graph.py`, `app/agents/world_builder.py`) import **only** from the package root:
`from app import safety` / `from app import multimodal`. Backend core shipped working stubs in `service.py`;
replace the internals freely, keep these signatures and return types (`app/schemas.py`).

### `app.safety`
```python
async def check_input(text: str, *, minor_mode: bool = False, rating: str = "teen", context: str = "turn") -> SafetyResult
    # context: "turn" | "world_prompt" | "source_text" | "inject" | "memory_query"
    # blocked=True → caller stops, emits SSE `safety` + `done {"blocked": true}`, commits nothing.
    # crisis=True → message must contain help hotline text.
async def check_output(text: str, *, minor_mode: bool = False, rating: str = "teen") -> SafetyResult
    # called on full narration / world JSON text after generation; caller persists `filtered_text`
    # (falls back to original if None). blocked=True → caller replaces narration with a safe notice.
def filter_chunk(text: str, *, minor_mode: bool = False) -> str
    # sync + fast; applied to every streamed token chunk before it is sent.
def policy() -> dict   # served by GET /api/safety/policy
CRISIS_MESSAGE: str
```
`SafetyResult = {allowed, blocked, crisis, categories: list[str], rating: "all"|"teen"|"mature", message, filtered_text}`.
LLM moderation: use `app.llm.client.chat_json(..., model=get_settings().fast_model)` (returns None without key → keyword only).
Reports (`POST /api/reports`) are stored by backend core in table `reports` (`app/db.py: ReportRow`).

#### 审核提速取舍（safety 同学，2026-10-19，用户已确认）
- **目标与平衡**：真实模式回合首字 ≤2s；一次 qwen-turbo 审核实测 1.1–3.9s，而且会加重 429 限流。因此不再逐条调大模型，改为“规则层兜底 + 可疑才调 LLM”。
- **规则层同步、不走捷径**：危机（自伤/自杀，返回热线）、违规硬拦截（关键词 + 正则）、提示词注入/越狱、未成年人禁用词、分级上限，全部在规则层同步判定，任何模式都不跳过。
- **可疑才调 LLM**：`turn` / `memory_query` / 生成文本中，规则层干净、文本短、没有可疑特征的直接放行。灰区词、疑似注入、变形混淆、链接/联系方式、长文本、危机暗示、超分级、未成年人敏感话题才调用 LLM。`world_prompt` / `source_text` / `inject` 调用频率低，始终调用 LLM。
- **严格时限**：turn/memory_query 1.5s，output 3s，低频场景 5s；超时按规则层结果处理，后台调用继续执行并写入缓存。
- **应对 429**：结果缓存（LRU + TTL 900s，key = sha256(minor_mode|kind|text)），同文本并发合并为一次调用，全局并发上限 2，调用间隔 ≥0.2s。高频场景在饱和时跳过 LLM、不排队；遇到 429 指数退避（5s→…≤120s），退避期间只走规则层。
- **可选并行快速路径**：`check_input_fast(...) -> (rule_result, review_task|None)` 先返回规则层结果，LLM 复核在后台运行；复核结果为 blocked/crisis 时回调 `on_flag`，由调用方中止流式输出、替换叙事或不提交。生成文本可用 `review_output(...)` 做后台复核。当前策略可在 `GET /api/safety/policy` 的 `moderation` 字段查看。

### `app.multimodal`
```python
async def illustrate(world_id: str, prompt: str, *, turn_id: str | None = None, style: str | None = None, force: bool = False) -> Asset
async def speak(world_id: str, text: str, *, voice: str | None = None, turn_id: str | None = None, force: bool = False) -> Asset
async def regenerate(asset_id: str) -> Asset | None      # same type/prompt, bypass cache, new file
def list_assets(world_id: str) -> list[Asset]
```
- Must never raise for API failure: fall back to placeholder (`source="fallback"`).
- Files go to `get_settings().assets_dir` (`backend/data/assets`), URL = `/api/static/assets/<file>` (mounted by `app/main.py`).
- Rows in table `assets` (`AssetRow`: id, world_id, type, url, turn_id, prompt, cache_key, source). Cache by `cache_key`.
- Settings available: `dashscope_api_key`, `dashscope_api_url` (native `https://dashscope.aliyuncs.com/api/v1`), `image_model`, `tts_model`, `tts_voice`, `llm_enabled`.
- Turn graph calls these only for key scenes (opening turn, chapter boundary, high-impact/injected event) — cost control lives in `app/graph/turn_graph.py`.

## Data / env
- `DASHSCOPE_API_KEY` is read only in `backend/app/config.py` (`Settings.dashscope_api_key`; env var or `backend/.env`).
- `ZM_FORCE_FALLBACK=1` → no remote calls at all (tests use this). `ZM_DATA_DIR` → alternative data dir (tests use tmp dirs).
- `ZM_DISABLE_IMAGE=1`（1/true/yes）→ 只返回占位插画 SVG（`source="fallback"`），不调用百炼生图，用于省费；配音与大模型不受影响。QA 跑真实模式测试时请设置它。读取方式见 `config.py` 的 `disable_image` / `image_enabled`；运行时状态见 `multimodal.status()`。

## QA / integration (engineer #4)
- Start everything: `scripts/dev.sh` (backend :8000 via `backend/.venv` + `uvicorn app.main:app`, frontend :3000 via `pnpm exec next dev`). `--fallback` forces `ZM_FORCE_FALLBACK=1`. Reads root `.env` (auto-created from `.env.example`); an already-exported `DASHSCOPE_API_KEY` wins. **Backend: please keep the entrypoint at `backend/app/main.py:app`** and `GET /api/health` fast.
- API smoke: `backend/.venv/bin/python -m pytest backend/tests/integration -q` (runs in-process with `ZM_FORCE_FALLBACK=1` + tmp `ZM_DATA_DIR`; set `ZM_API_BASE=http://localhost:8000` to hit a live server instead).
- E2E: `cd tests/e2e && pnpm test` against a running app (`ZM_WEB=http://localhost:3000`). Uses system Chrome.
- **Frontend: tests select by `data-testid` first, falling back to visible Chinese text.** Requested ids are listed in `tests/e2e/TESTIDS.md`.
- Bugs go to `BUGS.md` (owner, repro, expected, status). I re-test every ~10 min after `git pull`.

## Backend core notes (2026-10-19)
- Entry `backend/app/main.py:app`; routes in `backend/app/routes/*`; LangGraph turn graph `backend/app/graph/turn_graph.py`
  (`safety_in → memory → {world_agent ∥ npc_agents} → director → extract → persist`).
- Safety calls go through `app/services/guard.py` (signature-tolerant adapter; fail-safe keyword check if `app.safety` raises).
  Order: `check_input` → `filter_chunk` per streamed chunk (8-char hold-back) → `check_output` on full text → persist `filtered_text`.
- Multimodal: auto only for key scenes (`multimodal.is_key_scene`: turn 1, first turn of each chapter, injected/high-impact
  events, ending) + opening illustration on confirm; all calls pass `minor_mode` (`key_scene_assets` reads `world["minor_mode"]`).
- API.md v1.1 changelog lists contract changes (static path `/api/static/assets`, additive fields).
- Install deps: `cd backend && uv pip install --python .venv/bin/python -r requirements.txt` (or `-e .`).
- Backend core tests: `backend/.venv/bin/python -m pytest backend/tests/core -q`.
- v1.3 取舍（后端核心，2026-10-19）：按用户方针以“稳定可用、体验流畅”为先，首字 ≤2s / 世界预览 5s 不再继续投入
  （真实 key 实测：首字约 3.3–3.5s、预览约 3–7s，主要受百炼的限流和断流影响）。
  已接入 safety 的 `check_input_fast`：规则层照旧同步拦截，后台复核命中就中止流并不提交；提交前最多等复核 3s，超时按规则层结果放行。
  这样“拦截”可能在部分 token 之后才到，前端需要丢弃已显示的半段旁白（API.md v1.3）。
  关键场景媒体最多等 KEY_SCENE_MEDIA_DEADLINE_S（默认 3s；原 10s 会让关键场景回合的 done 推迟最多 10s，体验流畅优先改为 3s），之后给占位；回合流不会为等升级在 done 之后继续挂着（否则前端会一直处于 streaming 状态、无法输入），
  升级信号改为：仍在进行的回合流内推送，或用 `GET /api/assets/{id}?wait=8` 长轮询。
  资产 version/updated_at 由 db.py 的 AssetRow before_update 监听维护（multimodal 原地升级改了 url/source 就 +1），不需要改 multimodal 的代码。


## Frontend trade-offs（前端，2026-10-19）
按用户方针：计划书不死扣，优先等待/降级/报错体验与稳定可用。以下是前端主动做的取舍及理由。
- **代理超时（BUG-007）**：用 `experimental.proxyTimeout`（180s，Next 16.4 dev/start 均生效）而不是自写 route handler 代理——改动最小、SSE 不经二次缓冲；浏览器仍只连 `/api`。慢接口前端 fetch 超时 120s，普通 30s。
- **报错一律中文**：任何原始错误文本只进 console；界面按状态码/超时/断网给中文提示 + 重试入口。宁可信息少一点，也不把 "Internal Server Error" 抛给用户。
- **轮询都有上限，不做无限等待**：资产长轮询每个 id 只有一个循环（多组件共享），总预算约 3 分钟、连续错误 4 次即停，页面离开即 abort；超时就停在占位（仍可手动「重绘/重新生成」）。学习小结 pending 最多重取 6 次（约 48s）后保留本地版并给「再试一次」；预览「细节补全中」最多轮询约 3 分钟，且补全期间允许直接进入世界（世界已可玩，没必要让用户干等）。
- **开局媒体不再走列表轮询到底**：`/assets` 列表只轮询到开局占位出现（v1.3 约 1s），之后按 id 用 `?wait=8` 长轮询；细节补全改写开场期间才低频（每 3 次）再拉列表找新的一组。去掉了前端自己调 tts 的开局兜底（后端已负责）。
- **资产升级的显示**：图片在新文件加载完成后才淡入替换（避免闪白/空帧）；音频正在播放时不热切换，播完（或暂停后下次播放）才换新源——热切换会打断用户正在听的内容。`pending` 的静音占位不自动播放；自动播放每个资产只触发一次（升级后不会突然再响一遍）。`ready + fallback` 视为最终占位：停止轮询，标注「占位」并给「重新生成」。
- **半途拦截**：收到 `safety(blocked)` / `done{blocked}` 立即清空已显示和打字机缓冲中的半段旁白，之后的 token 一律丢弃；不提交、不入历史/存档，同时清除本地待重试的请求体（同一输入重试仍会被拦）。不做「已撤回原文」之类展示，避免放大被拦内容。
- **事后替换的旁白**：服务端为准，但不持续轮询 `/turns`（收益低、请求多）。同步时机：首次加载/刷新、每回合结束后的侧栏刷新、回合结束约 12s 后再同步一次（覆盖后台复核的常见耗时）、标签页回到前台。替换是静默覆盖，不额外弹提示。
- **模型降级可见但不打扰**：回合 `source:"fallback"` 显示小标签「本地叙事」；流中 `fallback+reset` 时清空并提示「已改由本地叙事模板重新讲述」。兜底模式下每回合都会带这个标签——这是如实标注，不隐藏。
- **mock 回归用例**：兜底后端产生不了的状态（pending 升级、半途拦截、事后替换、播放中换源、离开页面中止）用完全 mock `/api` 的 Playwright 用例覆盖（`frontend/tests`，`pnpm test:mock`），不依赖 :8000，QA 重启后端也不受影响。"播放中"用改写 `paused` 属性模拟，真实播放的听感未自动化，需人工抽查。
- **可见 AI 标识默认隐藏（用户要求，2026-10-19）**：所有可见的「内容由AI生成」/「AI 生成」/「AI 编排」/占位图角标/海报与短视频标识文字统一由开关控制——前端 `NEXT_PUBLIC_ZM_SHOW_AI_LABEL`（构建期，默认关，`AiLabel` 直接返回 null，不留空位），后端 `ZM_SHOW_AI_LABEL`（占位 SVG 角标、万相水印默认跟随）。后端 `ai_generated`/`ai_label` 字段、`ai_meta` 与 PNG 隐式元数据保持不变，`=1` 即可整体恢复。相关测试按开关条件断言。公开上线若需满足显式标识要求，请打开开关。

## 用户系统接口契约（feat/auth，草案 v1）

> 状态：**草案 v1（API v1.4-draft）**，2026-10-28，后端核心。只定契约，后端实现随后在 `feat/auth` 分支完成。前端可以先按本节 mock 对接。
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
请求体为空。返回 200 `{"ok": true}`，清除两个 cookie，并吊销当前 refresh 所在的 family。没有登录时调用也返回 200。

#### 3.4 `POST /api/auth/refresh`（公开，需要 `zm_refresh` cookie）
请求体为空。返回 200 `{"user": User}` 并 Set-Cookie 新的两个 cookie。
错误：401 `refresh_invalid`（缺失、过期、已作废、被重放、或修改密码后 `ver` 不匹配），同时清除 cookie。

#### 3.5 `GET /api/auth/me`（公开）
```json
// 已登录
{ "authenticated": true, "user": User, "auth_required": false }
// 未登录（不返回 401，避免控制台报错）。ZM_AUTH_REQUIRED=0 时 acting_as 为 demo，此时匿名请求的数据都记在 demo 名下
{ "authenticated": false, "user": null, "auth_required": false, "acting_as": { "id": "u_demo", "username": "demo", "nickname": "演示账号" } }
// ZM_AUTH_REQUIRED=1 且未登录
{ "authenticated": false, "user": null, "auth_required": true, "acting_as": null }
```
带了 `zm_access` 但已过期或无效时返回 401 `token_expired`，前端据此去调 refresh。

#### 3.6 `PATCH /api/users/me`（需登录）
```json
{ "nickname": "小雨", "bio": "喜欢民国悬疑", "email": "new@example.com", "current_password": "Dream2026!" }
// 字段都可选；email 传 null 表示删除。修改或删除 email 必须同时带 current_password
// 200
{ "user": User }
```
错误：401 `unauthorized` / `token_expired` · 422 `validation_error` · 409 `email_taken` · 401 `invalid_password`（修改邮箱时 current_password 错误）· 403 `demo_readonly`（demo 账号不能改资料、密码、头像和邮箱，偏好可以改）。

#### 3.7 `PUT /api/users/me/password`（需登录）
```json
{ "current_password": "Dream2026!", "new_password": "Weave#Dream88" }
// 200 → token_version+1：其它设备全部下线，本设备重新签发 cookie
{ "ok": true }
```
错误：401 `invalid_password` · 400 `weak_password` · 400 `same_password` · 403 `demo_readonly` · 429 `rate_limited`（连续 5 次输错当前密码，锁 5 分钟）。

#### 3.8 `POST /api/users/me/avatar`（需登录，`multipart/form-data`，字段名 `file`）
- 只接受 `image/png`、`image/jpeg`、`image/webp`，按文件头判断真实类型，不信任扩展名和 Content-Type。大小不超过 **2 MB**，边长不超过 4096。
- 服务端居中裁成正方形，缩放到 256×256，重新编码为 webp（同时去掉 EXIF），存为 `$ZM_DATA_DIR/avatars/<user_id>_<rand>.webp`，旧文件删除。
```json
// 200
{ "avatar_url": "/api/static/avatars/u_3f2a9c1b7d4e_8k2j.webp", "user": User }
```
错误：413 `file_too_large` · 415 `unsupported_media_type` · 400 `invalid_image`（文件损坏或超过 4096 边长）· 403 `demo_readonly`。
`DELETE /api/users/me/avatar` → 200 `{ "avatar_url": null, "user": User }`。没有头像时，前端用 nickname 首字显示默认头像。

#### 3.9 `GET /api/users/me/preferences` / `PATCH /api/users/me/preferences`（需登录；`ZM_AUTH_REQUIRED=0` 时匿名请求读写 demo 的偏好）
```json
// GET 200
{ "preferences": Preferences }
// PATCH：部分合并（education 也是部分合并）
{ "minor_mode": true, "tts_enabled": false, "education": { "grade": "初二" } }
// 200
{ "preferences": Preferences }
```
未成年人模式从 **true 改为 false** 必须同时带 `"current_password"`，作为家长确认。没带或错误返回 401 `invalid_password`；demo 账号不能关闭，返回 403 `demo_readonly`。打开（变严格）不需要密码。
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
  "learning": { "worlds": 2, "turns": 23, "knowledge_cards": 17,
                "recent": [ { "world_id": "w_ab12", "title": "赤壁怀古", "subject": "语文", "grade": "初二", "turns": 12, "cards": 9,
                              "updated_at": "2026-10-27T12:00:00+00:00",
                              "summary": { "key_points": ["…"], "reflection": "…", "source": "llm", "turn_count": 12,
                                           "generated_at": "2026-10-27T12:01:00+00:00" } } ] },
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
- `learning.recent`：最近 5 个教育世界，`subject` / `grade` 取自 `state.flags.edu`。
- `learning.recent[].summary`：**最近一次已生成的学习小结**。实现阶段会把 `GET /education/summary` 得到的 `status:"complete"` 结果持久化到 `state.flags.edu_summary`（目前只在内存缓存里，重启就丢）。从没生成过时为 `null`，前端可以显示「生成学习小结」按钮，点击后去调 `/education/summary`。
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
  - `/api/users/me/*`。PATCH 资料、密码、头像这几个接口**始终要求真实登录**：即使 `ZM_AUTH_REQUIRED=0`，匿名请求也返回 401 `unauthorized`。preferences 和 stats 在模式 0 下匿名请求作用于 demo。
- **公开接口**：`/api/health`（新增 `"auth": {"required": bool}`）、`/api/safety/policy`、`/api/safety/check`、`/api/auth/register|login|logout|refresh|me`、静态文件。
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
| 401 | `invalid_password` | 修改密码、邮箱、关闭未成年人模式时，当前密码错误 |
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
1. `lib/api.ts` 和 `lib/sse.ts`：所有请求加 `credentials:"include"`。统一包一层：收到 401 `token_expired` 时先 `POST /api/auth/refresh`（并发请求共享同一个 refresh promise），然后重试**一次**；refresh 返回 `refresh_invalid` 就清除登录态。SSE 在建立前也可能收到 401，同样处理。
2. 新增页面：`/login`、`/register`（用户名、密码、可选邮箱、昵称；按 `field` 把错误显示到对应字段下；429 时按 `retry_after` 倒计时）、`/me` 个人中心（资料编辑、头像上传带裁剪预览、修改密码、偏好设置、统计面板、最近世界、学习记录）。
3. 全局：启动时调 `GET /api/auth/me`，顶栏显示头像和昵称或「登录」按钮；`auth_required:true` 且未登录时，访问受保护页面跳转 `/login?next=`；`auth_required:false` 且未登录时，显示提示条「当前为演示账号，登录后保存到你自己的账号」。
4. 世界或资产返回 404 时，沿用现有的「找不到对应的内容」提示（别人的世界也是 404）。
5. 生成表单和教育表单里 `minor_mode`、`rating`、`grade`、`subject` 的默认值改为读用户偏好；偏好开启未成年人模式时，世界设置页里「关闭未成年人模式」的开关置灰。看到 `X-ZM-Clamped` 响应头时给出提示。
6. 配音：`preferences.tts_enabled=false` 时隐藏或不播放音频，`autoplay_audio` 控制是否自动播放。
7. 登出后清空本地缓存（世界列表、待重试的回合请求体等）。
8. 建议新增 data-testid（交给 QA 写进 `tests/e2e/TESTIDS.md`）：`auth-username`、`auth-password`、`auth-email`、`auth-submit`、`auth-error`、`user-menu`、`logout-btn`、`profile-nickname`、`profile-bio`、`avatar-upload`、`pref-minor-mode`、`stats-panel`。
