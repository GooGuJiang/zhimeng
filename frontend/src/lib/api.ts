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
    /** raw server/proxy text, for logs only — never shown to users */
    public raw?: string,
  ) {
    super(message);
  }
}

/** Client-side request timeouts. Must exceed the slowest backend call (real-model LLM + retries). */
export const TIMEOUT = { normal: 30_000, slow: 120_000 };

const hasCJK = (s: string) => /[\u4e00-\u9fff]/.test(s);

/** Map a failed response to a user-facing Chinese message (never the raw "Internal Server Error"). */
export function friendlyMessage(status: number, detail?: string): string {
  if (detail && hasCJK(detail) && status < 500) return detail; // backend 4xx details are written for users
  if (status === 400 || status === 422) return "请求内容未通过校验，请修改后再试";
  if (status === 404) return "找不到对应的内容，它可能已被删除";
  if (status === 409) return "操作冲突，请刷新后重试";
  if (status === 429) return "请求太频繁了，请稍等片刻再试";
  if (status === 504 || status === 408) return "AI 思考得太久，暂时没有回应，请稍后重试";
  if (status >= 500) return "服务暂时繁忙（AI 可能仍在生成），请稍后重试";
  return `请求失败（${status}），请重试`;
}

/** Normalise anything thrown by fetch/request into a friendly message. */
export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  const name = (e as { name?: string })?.name;
  if (name === "TimeoutError") return "等待时间过长，AI 仍未完成，请稍后重试";
  if (name === "AbortError") return "请求已取消";
  if (name === "TypeError") return "网络连接异常，请检查后端服务后重试"; // fetch network failure
  const msg = (e as Error)?.message ?? "";
  return hasCJK(msg) ? msg : "操作失败，请重试";
}

export async function toApiError(res: Response): Promise<ApiError> {
  let detail: string | undefined;
  let code: string | undefined;
  let raw = res.statusText;
  try {
    const text = await res.text();
    raw = text || raw;
    const body = JSON.parse(text);
    detail = typeof body.detail === "string" ? body.detail : undefined;
    code = body.code;
  } catch {
    /* not json (e.g. proxy "Internal Server Error") */
  }
  return new ApiError(friendlyMessage(res.status, detail), res.status, code, raw);
}

/** Resolve a backend-relative asset url ("/api/static/assets/..."). */
export function assetUrl(url: string | null | undefined): string {
  if (!url) return "";
  if (/^(https?:|data:|blob:)/.test(url)) return url;
  return `${API_BASE}${url.startsWith("/") ? "" : "/"}${url}`;
}

type Init = RequestInit & { json?: unknown; timeout?: number };

async function request<T>(path: string, init?: Init): Promise<T> {
  const { json, timeout = TIMEOUT.normal, ...rest } = init ?? {};
  const signals = [AbortSignal.timeout(timeout), rest.signal].filter(Boolean) as AbortSignal[];
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api${path}`, {
      ...rest,
      signal: signals.length > 1 && "any" in AbortSignal ? AbortSignal.any(signals) : signals[0],
      headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...rest.headers },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch (e) {
    throw new ApiError(errorText(e), 0, (e as Error)?.name, String(e));
  }
  if (!res.ok) {
    const err = await toApiError(res);
    console.warn(`[api] ${path} → ${res.status}`, err.raw?.slice(0, 300));
    throw err;
  }
  return (await res.json()) as T;
}

const slow = { timeout: TIMEOUT.slow };

export const api = {
  health: () =>
    request<{
      status: string;
      llm: boolean;
      fallback?: boolean;
      models: Record<string, string | string[]>;
      llm_runtime?: { last_model: string | null; switches: number; cooling: string[] };
      version: string;
    }>("/health"),
  listWorlds: () => request<WorldSummary[]>("/worlds"),
  getWorld: (id: string) => request<World>(`/worlds/${id}`),
  deleteWorld: (id: string) => request<{ ok: boolean }>(`/worlds/${id}`, { method: "DELETE" }),
  confirmWorld: (id: string) => request<World>(`/worlds/${id}/confirm`, { method: "POST", ...slow }),
  patchSettings: (id: string, body: { minor_mode?: boolean; rating?: Rating }) =>
    request<World>(`/worlds/${id}/settings`, { method: "PATCH", json: body }),
  createWorld: (body: GenerateWorldRequest) =>
    request<World>("/worlds", { method: "POST", json: body, ...slow }),

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
      ...slow,
      method: "POST",
      json: { question, top_k },
    }),
  summaries: (id: string) =>
    request<{ chapter: number; from_turn: number; to_turn: number; summary: string }[]>(
      `/worlds/${id}/summaries`,
    ),

  assets: (id: string) => request<Asset[]>(`/worlds/${id}/assets`),
  illustrate: (id: string, body: { turn_id?: string; prompt?: string }) =>
    request<Asset>(`/worlds/${id}/assets/illustration`, { method: "POST", json: body, ...slow }),
  tts: (id: string, body: { text: string; voice?: string; turn_id?: string }) =>
    request<Asset>(`/worlds/${id}/assets/tts`, { method: "POST", json: body, ...slow }),
  regenerateAsset: (assetId: string) =>
    request<Asset>(`/assets/${assetId}/regenerate`, { method: "POST", ...slow }),

  ui: (id: string, focus?: string) =>
    request<{ components: UIComponent[] }>(
      `/worlds/${id}/ui${focus ? `?focus=${encodeURIComponent(focus)}` : ""}`,
      slow,
    ),

  npcs: (id: string) => request<NpcView[]>(`/worlds/${id}/god/npcs`),
  inject: (
    id: string,
    body: { content: string; target_character_ids?: string[]; location_id?: string; impact?: string },
  ) => request<WorldEvent>(`/worlds/${id}/god/inject`, { method: "POST", json: body, ...slow }),
  tick: (id: string) =>
    request<{ events: WorldEvent[] }>(`/worlds/${id}/god/tick`, { method: "POST", ...slow }),

  exportSave: (id: string) => request<Record<string, unknown>>(`/worlds/${id}/export`, slow),
  importSave: (save: unknown) => request<World>("/worlds/import", { method: "POST", json: save, ...slow }),
  poster: (id: string) => request<Poster>(`/worlds/${id}/poster`, slow),

  safetyCheck: (text: string, minor_mode?: boolean) =>
    request<SafetyResult>("/safety/check", { method: "POST", json: { text, minor_mode } }),
  policy: () =>
    request<{ ratings: unknown[]; minor_mode: unknown; crisis_message: string; ai_label: string }>(
      "/safety/policy",
    ),
  /** v1.2: world-scoped list (GET without world_id is admin-only → 403 forbidden). */
  reports: (worldId: string) =>
    request<
      {
        id: string;
        world_id?: string;
        reason?: string;
        status?: string;
        created_at?: string;
        priority?: string;
      }[]
    >(`/reports?world_id=${encodeURIComponent(worldId)}`),
  report: (body: { world_id?: string; turn_id?: string; content: string; reason: string }) =>
    request<{ id: string; status: string; created_at: string; priority?: "high" | "normal" }>("/reports", {
      method: "POST",
      json: body,
    }),

  eduCards: (id: string) => request<KnowledgeCard[]>(`/worlds/${id}/education/cards`),
  eduSummary: (id: string) => request<EducationSummary>(`/worlds/${id}/education/summary`, slow),
};

export const streamPath = {
  generate: "/worlds/generate",
  regenerate: (id: string) => `/worlds/${id}/regenerate`,
  turn: (id: string) => `/worlds/${id}/turns`,
  retry: (id: string) => `/worlds/${id}/turns/retry`,
  uiStream: (id: string) => `/worlds/${id}/ui/stream`,
  education: "/education/generate",
};
