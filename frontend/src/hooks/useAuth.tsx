"use client";
/**
 * Session state for the whole app (contract v1.4 §「用户系统」).
 * - GET /api/auth/me once on load: 200 → signed in; 401 → anonymous, carrying `auth_required` and, in demo
 *   mode (ZM_AUTH_REQUIRED=0), `acting_as` (the demo account anonymous requests act as).
 * - Session loss (refresh failed → AUTH_LOST_EVENT from lib/api) = logout.
 * - Logout / account switch clears per-account local state; other tabs follow via BroadcastChannel.
 * - On sign-in the account preferences are mirrored into local prefs (minor mode, auto voice).
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { authApi, type ActingAs, type Preferences, type User } from "@/lib/auth";
import { ApiError, AUTH_CHECK_EVENT, AUTH_LOST_EVENT } from "@/lib/api";
import { clearAccountLocalState } from "@/lib/storage";
import { setCurrentWorld } from "@/hooks/useCurrentWorld";
import { patchLocalPrefs } from "@/hooks/usePrefs";

export type AuthStatus = "loading" | "authed" | "anon" | "offline";
interface AuthCtx {
  status: AuthStatus;
  user: User | null;
  /** server requires a login for everything (ZM_AUTH_REQUIRED=1); false = demo mode */
  authRequired: boolean;
  /** demo mode: the account anonymous requests act as */
  actingAs: ActingAs | null;
  /**
   * The session was lost mid-use (refresh failed), or an action (write request) was refused with 401
   * `unauthorized` — guards send the user to /login?next even from public pages.
   */
  lost: boolean;
  refresh: () => Promise<User | null>;
  /** after login / register / profile edits */
  setUser: (u: User | null) => void;
  logout: () => Promise<void>;
}
const Ctx = createContext<AuthCtx | null>(null);
const CHANNEL = "zhimeng.auth";

export function mirrorPrefs(p: Preferences | undefined) {
  if (!p) return;
  patchLocalPrefs({
    minorMode: !!p.minor_mode,
    ttsEnabled: p.tts_enabled !== false,
    autoVoice: !!(p.tts_enabled && p.autoplay_audio),
  });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [authRequired, setAuthRequired] = useState(false);
  const [actingAs, setActingAs] = useState<ActingAs | null>(null);
  const [lost, setLost] = useState(false);
  const bc = useRef<BroadcastChannel | null>(null);
  const lastId = useRef<string | null | undefined>(undefined);

  const apply = useCallback((u: User | null) => {
    // switching accounts (or signing out) must not carry the previous person's current world / drafts
    if (lastId.current !== undefined && lastId.current !== (u?.id ?? null) && lastId.current !== null) {
      clearAccountLocalState();
      setCurrentWorld(null);
    }
    if (u && lastId.current !== u.id) mirrorPrefs(u.preferences);
    lastId.current = u?.id ?? null;
    setUserState(u);
    setStatus(u ? "authed" : "anon");
    if (u) setLost(false);
  }, []);

  const refresh = useCallback(
    () =>
      authApi.session().then(
        (s) => {
          setAuthRequired(s.authRequired);
          setActingAs(s.actingAs);
          apply(s.user);
          return s.user;
        },
        (e) => {
          // network / 5xx: we do not know — show an offline state where it matters
          if (!(e instanceof ApiError) || e.status === 0 || e.status >= 500) setStatus("offline");
          else apply(null);
          return null;
        },
      ),
    [apply],
  );

  useEffect(() => {
    void refresh();
    const onLost = () => {
      setLost(true);
      apply(null);
      bc.current?.postMessage("changed");
    };
    const onCheck = (e: Event) => {
      const method = (e as CustomEvent<{ method?: string }>).detail?.method ?? "GET";
      void refresh().then((u) => {
        if (!u && method !== "GET") setLost(true); // the user tried to do something that needs an account
      });
    };
    window.addEventListener(AUTH_LOST_EVENT, onLost);
    window.addEventListener(AUTH_CHECK_EVENT, onCheck);
    let ch: BroadcastChannel | null = null;
    if (typeof BroadcastChannel !== "undefined") {
      ch = new BroadcastChannel(CHANNEL);
      bc.current = ch;
      ch.onmessage = () => void refresh();
    }
    return () => {
      window.removeEventListener(AUTH_LOST_EVENT, onLost);
      window.removeEventListener(AUTH_CHECK_EVENT, onCheck);
      ch?.close();
    };
  }, [refresh, apply]);

  const setUser = useCallback(
    (u: User | null) => {
      apply(u);
      bc.current?.postMessage("changed");
    },
    [apply],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout(); // 204
    } catch {
      /* the UI must not keep showing the account even if the call failed */
    }
    clearAccountLocalState();
    setCurrentWorld(null);
    setUser(null);
  }, [setUser]);

  const value = useMemo(
    () => ({ status, user, authRequired, actingAs, lost, refresh, setUser, logout }),
    [status, user, authRequired, actingAs, lost, refresh, setUser, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}

/** 429 countdown: `start(retry_after)`; `left` > 0 while the submit button must stay disabled. */
export function useCooldown() {
  const [until, setUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!until) return;
    const t = window.setInterval(() => {
      const n = Date.now();
      setNow(n);
      if (n >= until) {
        setUntil(0);
        window.clearInterval(t);
      }
    }, 250);
    return () => window.clearInterval(t);
  }, [until]);
  const left = until ? Math.max(0, Math.ceil((until - now) / 1000)) : 0;
  const start = useCallback((sec: number) => {
    const n = Date.now();
    setNow(n);
    setUntil(n + Math.max(1, Math.ceil(sec)) * 1000);
  }, []);
  return { left, start };
}
