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
