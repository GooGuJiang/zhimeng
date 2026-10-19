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
