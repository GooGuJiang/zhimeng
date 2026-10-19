"use client";
/** The "current world" id lives in localStorage so a refresh (or a new tab) resumes it (AC-8). */
import { useCallback, useSyncExternalStore } from "react";
import { store } from "@/lib/storage";

const listeners = new Set<() => void>();
function subscribe(fn: () => void) {
  listeners.add(fn);
  window.addEventListener("storage", fn);
  return () => {
    listeners.delete(fn);
    window.removeEventListener("storage", fn);
  };
}

export function setCurrentWorld(id: string | null) {
  store.setWorldId(id);
  listeners.forEach((l) => l());
}

export function useCurrentWorld(): [string | null, (id: string | null) => void] {
  const id = useSyncExternalStore(
    subscribe,
    () => store.getWorldId(),
    () => null,
  );
  const set = useCallback((v: string | null) => setCurrentWorld(v), []);
  return [id, set];
}
