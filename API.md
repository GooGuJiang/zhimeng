# 织梦 Backend API Contract (v1)

Base URL: `http://localhost:8000` · all routes prefixed with `/api` · CORS allows `http://localhost:3000` (and 127.0.0.1:3000).
JSON everywhere (UTF-8). Errors: HTTP 4xx/5xx with `{"detail": "...", "code": "..."}`.
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
(v1.3: waits at most 10 s, then sends placeholders with `status:"pending"`; the same ids upgrade in place later). Fallback: SVG illustration / silent WAV placeholder.

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
- Illustration / tts / regenerate endpoints use an 8 s deadline (placeholder + background in-place upgrade); key-scene media waits ≤10 s;
  opening image/audio placeholders appear ~1 s after confirm and upgrade in place.
- Upgrade signal inside open turn streams: `asset` event with the same id, `status:"ready"` (also for this turn's key-scene assets).
- Turn input safety fast path (`safety` + `done{blocked:true}` may now arrive after some `token`s); post-commit narration review.
- Graceful shutdown waits ≤10 s for background asset upgrades.
