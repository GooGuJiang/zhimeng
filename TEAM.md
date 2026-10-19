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
