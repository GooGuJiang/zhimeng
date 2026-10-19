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
