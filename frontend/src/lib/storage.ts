/** Small localStorage helpers: current world id + local preferences survive refresh (AC-8). */
const KEY_WORLD = "zhimeng.currentWorld";
const KEY_PREFS = "zhimeng.prefs";
const KEY_DRAFT = (id: string) => `zhimeng.pending.${id}`;

export interface Prefs {
  minorMode: boolean;
  reducedMotion: "system" | "on" | "off";
  autoVoice: boolean;
  fontScale: number;
  /** colour theme; light ("宣纸") is the default */
  theme: "light" | "dark" | "system";
}
export const defaultPrefs: Prefs = {
  minorMode: false,
  reducedMotion: "system",
  autoVoice: false,
  fontScale: 1,
  theme: "light",
};

const safe = <T>(fn: () => T, fallback: T): T => {
  try {
    return typeof window === "undefined" ? fallback : fn();
  } catch {
    return fallback;
  }
};

export const store = {
  getWorldId: () => safe(() => localStorage.getItem(KEY_WORLD), null),
  setWorldId: (id: string | null) =>
    safe(() => (id ? localStorage.setItem(KEY_WORLD, id) : localStorage.removeItem(KEY_WORLD)), undefined),
  getPrefs: (): Prefs =>
    safe(() => ({ ...defaultPrefs, ...JSON.parse(localStorage.getItem(KEY_PREFS) ?? "{}") }), defaultPrefs),
  setPrefs: (p: Prefs) => safe(() => localStorage.setItem(KEY_PREFS, JSON.stringify(p)), undefined),
  /** An action the user sent whose turn did not commit yet (for retry after refresh). */
  getPending: (id: string) =>
    safe(
      () =>
        JSON.parse(localStorage.getItem(KEY_DRAFT(id)) ?? "null") as {
          action: string;
          option_id: string | null;
          client_turn_id: string;
        } | null,
      null,
    ),
  setPending: (id: string, v: { action: string; option_id: string | null; client_turn_id: string } | null) =>
    safe(
      () =>
        v ? localStorage.setItem(KEY_DRAFT(id), JSON.stringify(v)) : localStorage.removeItem(KEY_DRAFT(id)),
      undefined,
    ),
};

export const uid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
