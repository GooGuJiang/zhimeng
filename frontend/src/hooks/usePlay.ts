"use client";
/**
 * F2 play loop state machine.
 * - POST /turns as SSE; tokens are revealed by a typewriter so streaming always reads smoothly
 *   (instant under reduced motion).
 * - The sent body (with client_turn_id) is kept in localStorage until `done`, so a failed or
 *   interrupted turn — even across a refresh — is retried idempotently without losing progress.
 * - Generative UI comes from `ui` events / GET /ui; if absent it is derived locally from world state.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamPath, errorText } from "@/lib/api";
import { streamSSE } from "@/lib/sse";
import { store, uid } from "@/lib/storage";
import type {
  Asset,
  Citation,
  KnowledgeCard,
  Option,
  Progress,
  SafetyResult,
  Turn,
  UIComponent,
  World,
  WorldEvent,
  WorldState,
} from "@/lib/types";
import { fallbackComponents } from "@/openui/fallback";
import { worldCache } from "@/lib/cache";
import { isPending, mergeAssets, watchAsset } from "@/lib/assets";
import { useReducedMotion } from "./usePrefs";

export const TURN_STAGES = ["safety", "memory", "world", "npc", "director", "narrate", "extract", "persist"];

type TurnBody = { action: string; option_id: string | null; client_turn_id: string };

export interface LiveTurn {
  action: string;
  text: string; // revealed so far
  facts: Citation[];
  events: WorldEvent[];
  progress: Progress | null;
  rewrite: boolean;
  /** v1.2: narration was reset and is being re-told by the local template. */
  fallback?: boolean;
  /** v1.3: input flagged mid-stream; the partial narration was discarded. */
  blocked?: boolean;
}

const mergeById = <T extends { id: string }>(base: T[], add: T[]) => {
  const m = new Map(base.map((x) => [x.id, x]));
  for (const a of add) m.set(a.id, a);
  return [...m.values()];
};

export function usePlay(worldId: string) {
  const reduced = useReducedMotion();
  const [world, setWorld] = useState<World | null>(() => worldCache.get(worldId));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [options, setOptions] = useState<Option[]>([]);
  const [events, setEvents] = useState<WorldEvent[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [serverUi, setServerUi] = useState<UIComponent[] | null>(null);
  const [cards, setCards] = useState<KnowledgeCard[]>([]);
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [safety, setSafety] = useState<SafetyResult | null>(null);
  const [error, setError] = useState<{ message: string; retryable: boolean } | null>(null);
  const [pending, setPendingState] = useState<TurnBody | null>(null);

  const target = useRef(""); // full streamed text
  const committed = useRef<{ turn: Turn; state: WorldState; rewrite: boolean } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const [targetText, setTargetText] = useState("");

  const setPending = (p: TurnBody | null) => {
    store.setPending(worldId, p);
    setPendingState(p);
  };

  const syncTurns = useCallback((server: Turn[]) => {
    const byId = new Map(server.map((t) => [t.id, t]));
    setTurns((old) => {
      let changed = false;
      const next = old.map((t) => {
        const st = byId.get(t.id);
        if (st && (st.narration !== t.narration || st.ai_label !== t.ai_label)) {
          changed = true;
          return { ...t, ...st };
        }
        return t;
      });
      return changed ? next : old;
    });
  }, []);

  const refreshSide = useCallback(async () => {
    const [w, ev, ui, as, ts] = await Promise.allSettled([
      api.getWorld(worldId),
      api.events(worldId, "offscreen", 30),
      api.ui(worldId),
      api.assets(worldId),
      api.turns(worldId, 200),
    ]);
    // v1.3: committed narration may be replaced by post-commit review — the server copy wins for every
    // turn we already show (new turns are committed by the typewriter, so they're not added here).
    if (ts.status === "fulfilled") syncTurns(ts.value);
    if (w.status === "fulfilled") {
      worldCache.set(w.value);
      setWorld(w.value);
      if (w.value.mode === "education")
        api
          .eduCards(worldId)
          .then(setCards)
          .catch(() => {});
    }
    if (ev.status === "fulfilled") setEvents((old) => mergeById(old, ev.value));
    if (ui.status === "fulfilled" && ui.value.components?.length) setServerUi(ui.value.components);
    if (as.status === "fulfilled") setAssets((old) => mergeAssets(old, as.value));
  }, [worldId, syncTurns]);

  // ---- initial load ----
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const w = await api.getWorld(worldId);
        if (!live) return;
        worldCache.set(w);
        setWorld(w);
        const [ts, op] = await Promise.allSettled([api.turns(worldId, 200), api.options(worldId)]);
        if (!live) return;
        if (ts.status === "fulfilled") setTurns(ts.value);
        if (op.status === "fulfilled") setOptions(op.value.options ?? []);
        else if (ts.status === "fulfilled" && ts.value.length)
          setOptions(ts.value[ts.value.length - 1].options ?? []);
        else if (w.opening_options?.length) setOptions(w.opening_options); // v1.2 turn-0 options
        await refreshSide();
        const p = store.getPending(worldId);
        if (p) {
          setPendingState(p);
          setError({
            message: "上一次的行动没有完成（可能因刷新或网络中断），进度未受影响。",
            retryable: true,
          });
        }
      } catch (e) {
        if (live) setLoadError(errorText(e));
      } finally {
        if (live) setLoaded(true);
      }
    })();
    return () => {
      live = false;
      abort.current?.abort();
    };
  }, [worldId, refreshSide]);

  // v1.2: confirm generates the opening illustration + narrator audio in the background (turn_id=null,
  // no SSE asset event). Poll GET /assets with backoff until both exist (capped). Step-2 enrichment may
  // rewrite the opening and produce a newer pair, so keep polling (world + assets) while it is enriching.
  const hasOpeningTurn = turns.some((t) => t.index === 0);
  const openingImage = assets.some((a) => a.type === "image" && !a.turn_id);
  const openingAudio = assets.some((a) => a.type === "audio" && !a.turn_id);
  const enriching = world?.detail_status === "enriching";
  const needOpening = !hasOpeningTurn && (!openingImage || !openingAudio);
  useEffect(() => {
    if (!loaded || (!needOpening && !enriching)) return;
    let live = true;
    let n = 0;
    let delay = 1500;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (!live || ++n > 14) return; // ~2 min total with backoff
      // v1.3: placeholders exist ~1 s after confirm and are then long-polled by id, so the list is only
      // needed until the opening pair exists (or right after enrichment rewrote the opening).
      const [as, w] = await Promise.allSettled([
        needOpening || n % 3 === 0 ? api.assets(worldId) : Promise.resolve([] as Asset[]),
        enriching ? api.getWorld(worldId) : Promise.resolve(null),
      ]);
      if (!live) return;
      if (as.status === "fulfilled" && as.value.length) setAssets((old) => mergeAssets(old, as.value));
      if (w.status === "fulfilled" && w.value) {
        worldCache.set(w.value);
        setWorld(w.value);
      }
      delay = Math.min(10_000, Math.round(delay * 1.5));
      timer = setTimeout(tick, delay);
    };
    timer = setTimeout(tick, delay);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [loaded, needOpening, enriching, worldId]);

  // v1.3: every pending asset (opening, key scenes, manual illustrate/tts/regenerate placeholders, ones still
  // pending after `done`) is long-polled via GET /assets/{id}?wait=8 — one loop per id, aborted on unmount.
  const pendingIds = assets
    .filter(isPending)
    .map((a) => a.id)
    .sort()
    .join(",");
  const watching = useRef(new Map<string, () => void>());
  useEffect(() => {
    const want = new Set(pendingIds ? pendingIds.split(",") : []);
    const m = watching.current;
    for (const [id, off] of m)
      if (!want.has(id)) {
        off();
        m.delete(id);
      }
    for (const id of want)
      if (!m.has(id))
        m.set(
          id,
          watchAsset(id, (a) => setAssets((old) => mergeAssets(old, [a]))),
        );
  }, [pendingIds]);
  useEffect(() => {
    const m = watching.current;
    return () => {
      m.forEach((off) => off());
      m.clear();
    };
  }, []);

  // v1.3: re-pull history when the tab comes back (post-commit review may have replaced narration).
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible")
        api
          .turns(worldId, 200)
          .then(syncTurns)
          .catch(() => {});
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [worldId, syncTurns]);

  // ---- typewriter ----
  const typing = !!live && live.text.length < targetText.length;
  useEffect(() => {
    if (!live) return;
    if (live.text.length >= targetText.length) {
      // caught up: commit once the stream has finished
      if (!streaming && committed.current) {
        const { turn, state, rewrite } = committed.current;
        committed.current = null;
        setTurns((old) => {
          const rest = rewrite
            ? old.filter((t) => t.index !== turn.index)
            : old.filter((t) => t.id !== turn.id);
          return [...rest, turn].sort((a, b) => a.index - b.index);
        });
        setWorld((w) => (w ? { ...w, state } : w));
        setLive(null);
      } else if (!streaming && !committed.current) {
        setLive(null);
      }
      return;
    }
    const id = requestAnimationFrame(() => {
      setLive((l) => {
        if (!l) return l;
        if (reduced) return { ...l, text: targetText };
        const rem = targetText.length - l.text.length;
        const step = Math.max(1, Math.ceil(rem / 26));
        return { ...l, text: targetText.slice(0, l.text.length + step) };
      });
    });
    return () => cancelAnimationFrame(id);
  }, [live, streaming, targetText, reduced]);

  // ---- streaming a turn ----
  const runStream = useCallback(
    async (path: string, body: unknown, action: string, rewrite: boolean) => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      target.current = "";
      setTargetText("");
      committed.current = null;
      setSafety(null);
      setError(null);
      setStreaming(true);
      setLive({
        action,
        text: "",
        facts: [],
        events: [],
        progress: { stage: "safety", message: "落笔之前，先审一审", pct: 3 },
        rewrite,
      });
      let gotDone = false;
      let blocked = false;
      const dropNarration = () => {
        target.current = "";
        committed.current = null;
        setTargetText("");
        setLive((l) => (l ? { ...l, text: "", blocked: true } : l));
      };
      let newOptions: Option[] | null = null;
      try {
        await streamSSE(
          path,
          body,
          (event, data) => {
            const d = (data ?? {}) as Record<string, unknown>;
            switch (event) {
              case "progress":
                if (d.stage === "fallback" && d.reset) {
                  // v1.2 (BUG-006): the model stream broke; the server restarts with local-template
                  // narration — drop what was shown so far (done.turn.narration stays authoritative).
                  target.current = "";
                  setTargetText("");
                  setLive((l) =>
                    l ? { ...l, text: "", fallback: true, progress: d as unknown as Progress } : l,
                  );
                  break;
                }
                setLive((l) => (l ? { ...l, progress: d as unknown as Progress } : l));
                break;
              case "memory":
                setLive((l) => (l ? { ...l, facts: (d.facts as Citation[]) ?? [] } : l));
                break;
              case "event": {
                const evs = (d.events as WorldEvent[]) ?? [];
                setLive((l) => (l ? { ...l, events: mergeById(l.events, evs) } : l));
                setEvents((old) =>
                  mergeById(
                    old,
                    evs.filter((e) => e.type !== "player"),
                  ),
                );
                break;
              }
              case "token":
                if (blocked) break;
                target.current += String(d.text ?? "");
                setTargetText(target.current);
                break;
              case "options":
                newOptions = (d.options as Option[]) ?? [];
                break;
              case "ui": {
                const comps = (d.components as UIComponent[]) ?? [];
                if (comps.length) {
                  setServerUi((old) => mergeById(old ?? [], comps));
                }
                break;
              }
              case "asset":
                // v1.3: may arrive anywhere before `done`, including upgrades of older assets
                // (opening, earlier key scenes) — merge by id, newest version wins.
                setAssets((old) => mergeAssets(old, [d as unknown as Asset]));
                break;
              case "safety": {
                const s = d as unknown as SafetyResult;
                setSafety(s);
                if (s.blocked) {
                  // v1.3: may arrive after some tokens — drop the half narration (shown + buffered).
                  blocked = true;
                  dropNarration();
                }
                break;
              }
              case "error":
                setError({ message: String(d.message ?? "生成失败"), retryable: d.retryable !== false });
                break;
              case "done": {
                gotDone = true;
                if (d.blocked) {
                  blocked = true;
                  dropNarration();
                  break;
                }
                const turn = d.turn as Turn | undefined;
                const state = d.state as WorldState | undefined;
                if (turn) {
                  if (turn.narration && turn.narration !== target.current) {
                    target.current = turn.narration;
                    setTargetText(turn.narration);
                  }
                  committed.current = { turn, state: state ?? (world?.state as WorldState), rewrite };
                  // the 世界面板 / header reflect the new state right away (narration may still be typing)
                  if (state) setWorld((w) => (w ? { ...w, state } : w));
                  setOptions(newOptions ?? turn.options ?? []);
                }
                break;
              }
            }
          },
          ctrl.signal,
        );
        if (!gotDone && !ctrl.signal.aborted)
          setError((e) => e ?? { message: "连接意外中断，本回合未提交，进度安全。", retryable: true });
      } catch (e) {
        if (!ctrl.signal.aborted) setError({ message: errorText(e), retryable: true });
      } finally {
        setStreaming(false);
      }
      if (gotDone) {
        setPending(null);
        if (blocked) {
          target.current = "";
          setTargetText("");
          setLive(null);
        } else {
          // side panels (characters, items, events, GET /ui) reflect the committed turn;
          // without server UI the local fallback recomputes from the refreshed world.
          void refreshSide();
          // background narration review usually lands within seconds; re-sync once more later.
          setTimeout(() => {
            api
              .turns(worldId, 200)
              .then(syncTurns)
              .catch(() => {});
          }, 12_000);
        }
      } else {
        // nothing was committed: drop the partial narration, the pending body stays for retry.
        target.current = "";
        setTargetText("");
        setLive(null);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [worldId, refreshSide, syncTurns],
  );

  const busy = streaming || typing || !!live;

  const send = useCallback(
    (action: string, option_id: string | null = null) => {
      const a = action.trim();
      if (!a || busy) return false;
      const body: TurnBody = { action: a, option_id, client_turn_id: uid() };
      setPending(body);
      void runStream(streamPath.turn(worldId), body, a, false);
      return true;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [busy, runStream, worldId],
  );

  const retry = useCallback(() => {
    if (busy) return;
    const p = pending ?? store.getPending(worldId);
    if (p) void runStream(streamPath.turn(worldId), p, p.action, false);
    else setError(null);
  }, [busy, pending, runStream, worldId]);

  /** Regenerate the last committed turn from its pre-turn snapshot (POST /turns/retry). */
  const rewriteLast = useCallback(() => {
    if (busy || !turns.length) return;
    const last = turns[turns.length - 1];
    void runStream(streamPath.retry(worldId), {}, last.action, true);
  }, [busy, turns, runStream, worldId]);

  const dismissSafety = () => setSafety(null);
  const dismissError = () => {
    setError(null);
    setPending(null);
  };

  // ---- generative UI: server components, else local fallback; education cards merged in ----
  const base = world ? (serverUi?.length ? serverUi : fallbackComponents(world, events, options)) : [];
  let ui = base;
  if (world?.mode === "education") {
    const all = mergeById(world.knowledge_cards ?? [], cards);
    const existing = base.find((c) => c.type === "knowledge_cards");
    const merged = mergeById(
      ((existing?.props as { cards?: KnowledgeCard[] })?.cards ?? []).filter((c) => c && c.id),
      all,
    );
    const kc: UIComponent = existing
      ? { ...existing, props: { ...existing.props, cards: merged } }
      : {
          id: "knowledge",
          type: "knowledge_cards",
          title: "知识卡片",
          priority: 90,
          layout: { area: "side", size: "md" },
          props: { cards: merged },
          actions: [],
        };
    ui = [...base.filter((c) => c.type !== "knowledge_cards"), kc];
  }

  return {
    world,
    setWorld,
    loaded,
    loadError,
    turns,
    options,
    events,
    setEvents,
    assets,
    setAssets,
    ui,
    uiSource: (serverUi?.length ? "ai" : "local") as "ai" | "local",
    live,
    streaming,
    busy,
    safety,
    error,
    pending,
    send,
    retry,
    rewriteLast,
    dismissSafety,
    dismissError,
    refreshSide,
  };
}
