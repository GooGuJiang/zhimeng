"use client";
/** Local UI preferences (motion, font size, voice, default minor mode), persisted in localStorage. */
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { defaultPrefs, store, type Prefs } from "@/lib/storage";

const listeners = new Set<() => void>();
let cache: Prefs | null = null;

function read(): Prefs {
  if (!cache) cache = store.getPrefs();
  return cache;
}
function subscribe(fn: () => void) {
  listeners.add(fn);
  const onStorage = (e: StorageEvent) => {
    if (e.key === "zhimeng.prefs") {
      cache = null;
      fn();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(fn);
    window.removeEventListener("storage", onStorage);
  };
}

/** Update local prefs from outside React (e.g. account preferences synced on sign-in). */
export function patchLocalPrefs(patch: Partial<Prefs>) {
  cache = { ...read(), ...patch };
  store.setPrefs(cache);
  listeners.forEach((l) => l());
}

export function usePrefs(): [Prefs, (patch: Partial<Prefs>) => void] {
  const prefs = useSyncExternalStore(subscribe, read, () => defaultPrefs);
  const update = useCallback((patch: Partial<Prefs>) => {
    cache = { ...read(), ...patch };
    store.setPrefs(cache);
    listeners.forEach((l) => l());
  }, []);
  return [prefs, update];
}

/** Applies motion + font-scale preferences to <html>. Mounted once in the shell. */
export function useApplyPrefs() {
  const [prefs] = usePrefs();
  useEffect(() => {
    const html = document.documentElement;
    if (prefs.reducedMotion === "system") html.removeAttribute("data-motion");
    else html.setAttribute("data-motion", prefs.reducedMotion);
    html.style.setProperty("--font-scale", String(prefs.fontScale || 1));
  }, [prefs.reducedMotion, prefs.fontScale]);
  useEffect(() => {
    const html = document.documentElement;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = prefs.theme === "dark" || (prefs.theme === "system" && mq.matches);
      if (dark) html.setAttribute("data-theme", "dark");
      else html.removeAttribute("data-theme");
      document
        .querySelector('meta[name="theme-color"]')
        ?.setAttribute("content", dark ? "#0f1220" : "#f5f0e6");
    };
    apply();
    if (prefs.theme !== "system") return;
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [prefs.theme]);
}

/** True when animations should be skipped (user pref or OS setting). */
export function useReducedMotion(): boolean {
  const [prefs] = usePrefs();
  const os = useSyncExternalStore(
    (fn) => {
      const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
      mq.addEventListener("change", fn);
      return () => mq.removeEventListener("change", fn);
    },
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );
  if (prefs.reducedMotion === "on") return false;
  if (prefs.reducedMotion === "off") return true;
  return os;
}
