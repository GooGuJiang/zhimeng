/** In-memory hand-off of freshly generated worlds between routes (avoids a refetch flash). */
import type { World } from "./types";

const worlds = new Map<string, World>();
export const worldCache = {
  get: (id: string) => worlds.get(id) ?? null,
  set: (w: World) => void worlds.set(w.id, w),
};
