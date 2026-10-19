# 织梦 Backend API Contract (v1)

Base URL: `http://localhost:8000` · all routes prefixed with `/api` · CORS allows `http://localhost:3000` (and 127.0.0.1:3000).
JSON everywhere (UTF-8). Errors: HTTP 4xx/5xx with `{"detail": "...", "code": "..."}`.
Static generated assets: `GET /static/assets/<file>` (relative `url` fields below start with `/static/...`; prefix with base URL).

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
               ai_generated: true; ai_label: string }
type WorldSummary = { id; title; genre; tone; mode; turn: number; status; created_at; updated_at }
type Option = { id: string; text: string; hint?: string }
type WorldEvent = { id: string; world_id: string; type: "offscreen"|"world"|"player"|"injected"|"npc_action";
                    summary: string; actor_ids: string[]; location_id: string|null; turn: number; chapter: number;
                    impact: string; timestamp: string /* ISO */; in_world_time: string; seen: boolean }
type Citation = { fact_id: string; content: string; turn: number; chapter: number; kind: string; score: number; source: string /* e.g. "第2章·第5回合" */ }
type Turn = { id: string; world_id: string; index: number; chapter: number; action: string; narration: string;
              options: Option[]; events: WorldEvent[]; facts: string[]; asset_ids: string[]; key_scene: boolean;
              created_at: string; ai_generated: true; ai_label: string }
type Asset = { id: string; world_id: string; type: "image"|"audio"; url: string; turn_id: string|null;
               prompt: string; source: "dashscope"|"fallback"; created_at: string }
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
  layout: { area: "main" | "side" | "bottom"; size: "sm" | "md" | "lg" };
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
Action `kind: "turn"` → POST `/api/worlds/{id}/turns` with `payload` as body (`{action}`); `"navigate"` payload `{location_id}` → send as turn action `"前往<地点名>"` (payload contains ready `action` string too).

## Endpoints

### Health
`GET /api/health` → `{ "status": "ok", "llm": bool /* key configured */, "models": {"chat": str, "fast": str, "embedding": str, "image": str, "tts": str}, "version": str }`

### F1 World generation
`POST /api/worlds/generate` (SSE)
Body `GenerateWorldRequest`:
```json
{ "prompt": "一个民国上海滩的侦探故事，我是报社记者", "genre": "悬疑?", "tone": "?", "length": "short|medium|long", "language": "zh",
  "mode": "story", "source_text": null, "minor_mode": false, "rating": "teen" }
```
Events: `progress` (stages: `safety`,`outline`,`locations`,`characters`,`conflict`,`persist`,`memory`), `token` (optional raw text while LLM drafts), `world` (World), `safety` (if blocked), `done` `{ "world_id": str, "source": "llm"|"fallback" }`, `error`.
`POST /api/worlds` (non-streaming, same body) → `World`.
`POST /api/worlds/{id}/regenerate` (SSE, optional body overrides of GenerateWorldRequest) → regenerates the draft in place (same id; same events).
`POST /api/worlds/{id}/confirm` → `World` (status → `active`).
`GET /api/worlds` → `WorldSummary[]` · `GET /api/worlds/{id}` → `World` · `DELETE /api/worlds/{id}` → `{ "ok": true }`
`PATCH /api/worlds/{id}/settings` body `{ "minor_mode"?: bool, "rating"?: Rating }` → `World`

### F2 Play
`POST /api/worlds/{id}/turns` (SSE)
Body: `{ "action": "我去码头找线人", "option_id": "opt_2" | null, "client_turn_id": "uuid?" }`
(`client_turn_id` is an idempotency key: re-sending a committed id returns the committed turn as `done` immediately.)
Events in order: `progress`(stages `safety`,`memory`,`world`,`npc`,`director`,`narrate`,`extract`,`persist`) → `memory` → `event` → `token`* → `options` → `ui` → `asset`* (key scenes) → `done` `{ "turn": Turn, "state": WorldState }`.
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
Auto: turns flagged `key_scene` (opening, chapter boundary, injected/major events) emit `asset` events for image + audio. Fallback: SVG illustration / silent WAV placeholder.

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
`GET /api/reports` → list
Input blocked → turn/generate stream emits `safety` (blocked=true) then `done {"blocked": true}`; HTTP 200. Crisis content (self-harm etc.) → `safety` with `crisis=true` and `message` containing help hotline.

### F10 Education mode
`POST /api/education/generate` (SSE) body `{ "source_text": "课文/史料原文", "title"?: str, "subject"?: "语文|历史|非遗|...", "grade"?: str, "minor_mode"?: true }` → same events as world generation; World has `mode: "education"` and `knowledge_cards`.
`GET /api/worlds/{id}/education/cards` → `KnowledgeCard[]` (cards unlocked so far, incl. ones produced during turns)
`GET /api/worlds/{id}/education/summary` → `{ "title", "key_points": [str], "cards": KnowledgeCard[], "timeline": [{turn, summary}], "quiz": [{question, options: [str], answer_index: int, explanation}], "reflection": str, "ai_label": str }`
