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
