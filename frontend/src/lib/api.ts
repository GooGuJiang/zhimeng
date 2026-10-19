/**
 * Thin client for the FastAPI backend. All calls are same-origin (/api) and proxied by Next,
 * unless NEXT_PUBLIC_API_BASE points the browser at the backend directly. No keys live here.
 */
import type {
  Asset,
  Citation,
  EducationSummary,
  GenerateWorldRequest,
  MemoryEntry,
  NpcView,
  Option,
  Poster,
  Rating,
  SafetyResult,
  Turn,
  UIComponent,
  World,
  WorldEvent,
  WorldSummary,
  KnowledgeCard,
} from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}

/** Resolve a backend-relative asset url ("/static/..."). */
export function assetUrl(url: string | null | undefined): string {
  if (!url) return "";
  if (/^(https?:|data:|blob:)/.test(url)) return url;
  return `${API_BASE}${url.startsWith("/") ? "" : "/"}${url}`;
}

async function request<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(`${API_BASE}/api${path}`, {
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...rest.headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    let detail = res.statusText;
    let code: string | undefined;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
      code = body.code;
    } catch {
      /* not json */
    }
    throw new ApiError(detail || `请求失败 (${res.status})`, res.status, code);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () =>
    request<{
      status: string;
      llm: boolean;
      fallback?: boolean;
      models: Record<string, string>;
      version: string;
    }>("/health"),
  listWorlds: () => request<WorldSummary[]>("/worlds"),
  getWorld: (id: string) => request<World>(`/worlds/${id}`),
  deleteWorld: (id: string) => request<{ ok: boolean }>(`/worlds/${id}`, { method: "DELETE" }),
  confirmWorld: (id: string) => request<World>(`/worlds/${id}/confirm`, { method: "POST" }),
  patchSettings: (id: string, body: { minor_mode?: boolean; rating?: Rating }) =>
    request<World>(`/worlds/${id}/settings`, { method: "PATCH", json: body }),
  createWorld: (body: GenerateWorldRequest) => request<World>("/worlds", { method: "POST", json: body }),

  turns: (id: string, limit = 50) => request<Turn[]>(`/worlds/${id}/turns?limit=${limit}`),
  options: (id: string) => request<{ options: Option[] }>(`/worlds/${id}/options`),

  events: (id: string, type = "offscreen", limit = 50) =>
    request<WorldEvent[]>(`/worlds/${id}/events?type=${type}&limit=${limit}`),
  markSeen: (id: string, ids: string[]) =>
    request<{ ok: boolean }>(`/worlds/${id}/events/seen`, { method: "POST", json: { ids } }),

  memory: (id: string, kind = "", limit = 100) =>
    request<MemoryEntry[]>(`/worlds/${id}/memory?kind=${kind}&limit=${limit}`),
  queryMemory: (id: string, question: string, top_k = 5) =>
    request<{ answer: string; citations: Citation[]; ai_label: string }>(`/worlds/${id}/memory/query`, {
      method: "POST",
      json: { question, top_k },
    }),
  summaries: (id: string) =>
    request<{ chapter: number; from_turn: number; to_turn: number; summary: string }[]>(
      `/worlds/${id}/summaries`,
    ),

  assets: (id: string) => request<Asset[]>(`/worlds/${id}/assets`),
  illustrate: (id: string, body: { turn_id?: string; prompt?: string }) =>
    request<Asset>(`/worlds/${id}/assets/illustration`, { method: "POST", json: body }),
  tts: (id: string, body: { text: string; voice?: string; turn_id?: string }) =>
    request<Asset>(`/worlds/${id}/assets/tts`, { method: "POST", json: body }),
  regenerateAsset: (assetId: string) => request<Asset>(`/assets/${assetId}/regenerate`, { method: "POST" }),

  ui: (id: string, focus?: string) =>
    request<{ components: UIComponent[] }>(
      `/worlds/${id}/ui${focus ? `?focus=${encodeURIComponent(focus)}` : ""}`,
    ),

  npcs: (id: string) => request<NpcView[]>(`/worlds/${id}/god/npcs`),
  inject: (
    id: string,
    body: { content: string; target_character_ids?: string[]; location_id?: string; impact?: string },
  ) => request<WorldEvent>(`/worlds/${id}/god/inject`, { method: "POST", json: body }),
  tick: (id: string) => request<{ events: WorldEvent[] }>(`/worlds/${id}/god/tick`, { method: "POST" }),

  exportSave: (id: string) => request<Record<string, unknown>>(`/worlds/${id}/export`),
  importSave: (save: unknown) => request<World>("/worlds/import", { method: "POST", json: save }),
  poster: (id: string) => request<Poster>(`/worlds/${id}/poster`),

  safetyCheck: (text: string, minor_mode?: boolean) =>
    request<SafetyResult>("/safety/check", { method: "POST", json: { text, minor_mode } }),
  policy: () =>
    request<{ ratings: unknown[]; minor_mode: unknown; crisis_message: string; ai_label: string }>(
      "/safety/policy",
    ),
  report: (body: { world_id?: string; turn_id?: string; content: string; reason: string }) =>
    request<{ id: string; status: string; created_at: string; priority?: "high" | "normal" }>("/reports", {
      method: "POST",
      json: body,
    }),

  eduCards: (id: string) => request<KnowledgeCard[]>(`/worlds/${id}/education/cards`),
  eduSummary: (id: string) => request<EducationSummary>(`/worlds/${id}/education/summary`),
};

export const streamPath = {
  generate: "/worlds/generate",
  regenerate: (id: string) => `/worlds/${id}/regenerate`,
  turn: (id: string) => `/worlds/${id}/turns`,
  retry: (id: string) => `/worlds/${id}/turns/retry`,
  uiStream: (id: string) => `/worlds/${id}/ui/stream`,
  education: "/education/generate",
};
