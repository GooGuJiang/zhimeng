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

## 2. Endpoints I'm coding against (please confirm/rename in API.md)
- `POST /api/worlds/generate` body `{prompt, source_text?, genre?, tone?, length?, education_mode?, minor_mode?}` → **SSE**:
  `event: progress data:{stage, message, percent}` … `event: world data:<World>` … `event: done`. (`event: error data:{message, retryable}`)
- `POST /api/worlds/{id}/regenerate` (same SSE) ; `POST /api/worlds/{id}/confirm` → World
- `GET /api/worlds/{id}` → World (full state incl. characters, locations, inventory, stats, ui, turns/history)
- `POST /api/worlds/{id}/turns` body `{choice_id? , input?}` → **SSE**: `event: token data:{text}` (narration deltas),
  `event: options data:{options:[{id,text}]}`, `event: offscreen data:{events:[Event]}`, `event: state data:<partial World>`,
  `event: ui data:{panel, program}`, `event: asset data:{type:"image"|"audio", url, node_id}`, `event: safety data:{level, message}`, `event: done data:{turn_id}`
  Failure must not corrupt progress; frontend retries the same request (please make it idempotent per `client_turn_id` if possible).
- `GET /api/worlds/{id}/turns` → list of turns `{id, chapter, input, narration, options, created_at, assets}`
- `POST /api/worlds/{id}/memory/query` body `{question}` → `{answer, citations:[{turn_id, chapter, excerpt}]}`
- `GET /api/worlds/{id}/god` → `{npcs:[{id,name,mood,goal,location,recent_actions:[{t,summary}]}], timeline:[Event]}`
- `POST /api/worlds/{id}/god/inject` body `{event}` → `{event, accepted}` (recorded in memory)
- `GET /api/worlds/{id}/education` → `{cards:[{title, content, source?}], summary}`
- `GET /api/worlds/{id}/export` → JSON save; `POST /api/worlds/import` body = that JSON → World
- `POST /api/worlds/{id}/assets/regenerate` body `{node_id, type}`
- `POST /api/safety/report` body `{world_id?, turn_id?, reason, detail}`
- `GET /api/health`
- Static asset URLs should be under `/api/...` (e.g. `/api/assets/xxx.png`) so the Next rewrite proxies them.

## 3. CORS
Frontend proxies `/api/*` → `http://localhost:8000/api/*` via Next rewrites, so CORS is not required, but allowing
`http://localhost:3000` doesn't hurt. SSE responses: please send `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
