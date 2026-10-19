/**
 * v1.3 asset lifecycle helpers.
 * Assets upgrade in place (same id, higher `version`, new `url`); `status:"pending"` means the placeholder
 * is still being replaced; `ready` + `source:"fallback"` means real generation failed and the placeholder
 * is final.
 */
import { api, ApiError } from "./api";
import type { Asset } from "./types";

export const isPending = (a: Asset) => a.status === "pending";
/** Real generation failed: the placeholder is final (offer a manual regenerate). */
export const isFinalPlaceholder = (a: Asset) => a.status !== "pending" && a.source === "fallback";

const ver = (a: Asset) => a.version ?? 1;

/** Which of two copies of the same asset is newer (version, then updated_at, then incoming wins ties). */
export function newer(a: Asset | undefined, b: Asset): Asset {
  if (!a) return b;
  if (ver(b) !== ver(a)) return ver(b) > ver(a) ? b : a;
  if (a.status === "ready" && b.status === "pending") return a; // never downgrade
  if (a.updated_at && b.updated_at && b.updated_at < a.updated_at) return a;
  return b;
}

/** Merge by id, never letting a stale copy (older version / pending) overwrite a fresher one. */
export function mergeAssets(base: Asset[], add: Asset[]): Asset[] {
  const m = new Map(base.map((x) => [x.id, x]));
  let changed = false;
  for (const a of add) {
    if (!a || !a.id) continue;
    const cur = m.get(a.id);
    const pick = newer(cur, a);
    if (pick !== cur) {
      m.set(a.id, pick);
      changed = true;
    }
  }
  return changed ? [...m.values()] : base;
}

/* ---- long-poll watcher: one loop per asset id, shared by all subscribers ---- */
type Sub = (a: Asset) => void;
interface Watch {
  subs: Set<Sub>;
  ctrl: AbortController;
}
const watches = new Map<string, Watch>();

/** Total budget per watch: real image generation can take 10–30 s, tts 3–10 s; give it ~3 min. */
const MAX_MS = 180_000;
const MAX_ERRORS = 4;

async function loop(id: string, w: Watch) {
  const t0 = Date.now();
  let errors = 0;
  while (!w.ctrl.signal.aborted && Date.now() - t0 < MAX_MS) {
    try {
      const a = await api.asset(id, 8, w.ctrl.signal);
      errors = 0;
      w.subs.forEach((s) => s(a));
      if (!isPending(a)) break;
    } catch (e) {
      if (w.ctrl.signal.aborted) break;
      if (e instanceof ApiError && e.status === 404) break; // deleted / unknown: stop
      if (++errors > MAX_ERRORS) break;
      await new Promise((r) => setTimeout(r, 1500 * 2 ** errors)); // backoff on transient errors
    }
  }
  if (watches.get(id) === w) watches.delete(id);
}

/** Subscribe to upgrades of a pending asset. De-duplicated per id; aborted when the last subscriber leaves. */
export function watchAsset(id: string, onUpdate: Sub): () => void {
  let w = watches.get(id);
  if (!w) {
    w = { subs: new Set(), ctrl: new AbortController() };
    watches.set(id, w);
    void loop(id, w);
  }
  w.subs.add(onUpdate);
  const ww = w;
  return () => {
    ww.subs.delete(onUpdate);
    if (!ww.subs.size) {
      ww.ctrl.abort();
      if (watches.get(id) === ww) watches.delete(id);
    }
  };
}
