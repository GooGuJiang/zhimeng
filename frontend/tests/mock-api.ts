/** A tiny in-memory /api for Playwright: fixtures captured from the fallback backend + per-test overrides. */
import type { Page, Route } from "@playwright/test";
import world from "./fixtures/world.json";
import turns from "./fixtures/turns.json";
import options from "./fixtures/options.json";
import events from "./fixtures/events.json";
import ui from "./fixtures/ui.json";
import assets from "./fixtures/assets.json";
import health from "./fixtures/health.json";

export type Json = Record<string, unknown>;
export type Asset = (typeof assets)[number] & {
  status: "pending" | "ready";
  version: number;
  source: string;
};
export const WORLD_ID = world.id as string;
export const fixtures = { world, turns, options, events, ui, assets: assets as Asset[], health };

export const sse = (evs: [string, unknown][]) =>
  evs.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");

const svg = (label: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540"><rect width="100%" height="100%" fill="#1b2340"/><text x="40" y="80" fill="#e8d9a8" font-size="40">${label}</text></svg>`;

/** 0.2 s of silence as a valid PCM WAV. */
function wav(): Buffer {
  const n = 1600;
  const b = Buffer.alloc(44 + n * 2);
  b.write("RIFF", 0);
  b.writeUInt32LE(36 + n * 2, 4);
  b.write("WAVEfmt ", 8);
  b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20);
  b.writeUInt16LE(1, 22);
  b.writeUInt32LE(8000, 24);
  b.writeUInt32LE(16000, 28);
  b.writeUInt16LE(2, 32);
  b.writeUInt16LE(16, 34);
  b.write("data", 36);
  b.writeUInt32LE(n * 2, 40);
  return b;
}

export interface MockState {
  world: Json;
  turns: Json[];
  assets: Asset[];
  /** GET /api/assets/{id}?wait= handler; default: return the current copy from `assets`. */
  assetGet?: (id: string, call: number) => Promise<Asset | null> | Asset | null;
  /** Any other route; return undefined to fall through to the defaults. */
  extra?: (method: string, path: string, body: Json | null) => unknown | undefined;
  /** POST /turns body (SSE text); default: 404. */
  turnStream?: (body: Json) => string;
  log: { method: string; path: string; t: number }[];
}

export async function mockApi(page: Page, init: Partial<MockState> = {}): Promise<MockState> {
  const st: MockState = {
    world: structuredClone(world) as Json,
    turns: structuredClone(turns) as Json[],
    assets: structuredClone(assets) as Asset[],
    log: [],
    ...init,
  };
  const calls = new Map<string, number>();
  const json = (r: Route, body: unknown, status = 200) =>
    r.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/api/**", async (r) => {
    const url = new URL(r.request().url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = r.request().method();
    st.log.push({ method, path, t: Date.now() });
    const w = `/worlds/${WORLD_ID}`;
    if (path.startsWith("/static/assets/")) {
      const isWav = path.endsWith(".wav");
      return r.fulfill({
        status: 200,
        contentType: isWav ? "audio/wav" : "image/svg+xml",
        body: isWav ? wav() : svg(`${path.split("/").pop()}${url.search}`),
      });
    }
    const m = path.match(/^\/assets\/([^/]+)$/);
    if (m && method === "GET") {
      const n = (calls.get(m[1]) ?? 0) + 1;
      calls.set(m[1], n);
      const a = st.assetGet ? await st.assetGet(m[1], n) : st.assets.find((x) => x.id === m[1]);
      // emulate the server's long-poll so a pending answer doesn't make the client spin
      if (a?.status === "pending") await new Promise((res) => setTimeout(res, 400));
      return a ? json(r, a) : json(r, { detail: "not found", code: "not_found" }, 404);
    }
    if (st.extra) {
      let body: Json | null = null;
      try {
        body = r.request().postDataJSON() as Json;
      } catch {}
      const out = await st.extra(method, path, body);
      if (out !== undefined) return json(r, out);
    }
    if (path === "/health") return json(r, health);
    if (path === w && method === "GET") return json(r, st.world);
    if (path === `${w}/turns` && method === "GET") return json(r, st.turns);
    if (path === `${w}/turns` && method === "POST") {
      if (!st.turnStream) return json(r, { detail: "no stream", code: "not_found" }, 404);
      const body = r.request().postDataJSON() as Json;
      return r.fulfill({ status: 200, contentType: "text/event-stream", body: st.turnStream(body) });
    }
    if (path === `${w}/options`) return json(r, options);
    if (path === `${w}/events`) return json(r, events);
    if (path === `${w}/ui`) return json(r, ui);
    if (path === `${w}/assets`) return json(r, st.assets);
    if (path === "/worlds") return json(r, []);
    return json(r, [], 200);
  });
  await page.addInitScript((id) => {
    try {
      localStorage.setItem("zhimeng.currentWorld", id);
    } catch {}
  }, WORLD_ID);
  return st;
}

export const opening = (st: MockState, type: "image" | "audio") =>
  st.assets.find((a) => a.type === type && a.turn_id === null)!;

/** A ready, upgraded copy of an asset (new file + ?v=). */
export const upgraded = (a: Asset, version = (a.version ?? 1) + 1): Asset => ({
  ...a,
  status: "ready",
  source: "dashscope",
  version,
  url: a.url.replace(/(\.\w+)(\?.*)?$/, `_real$1?v=${version}`),
  updated_at: new Date().toISOString(),
});
export const pendingCopy = (a: Asset): Asset => ({ ...a, status: "pending", source: "fallback", version: 1 });
