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
