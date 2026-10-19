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
import { api, streamPath } from "@/lib/api";
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

  const refreshSide = useCallback(async () => {
    const [w, ev, ui, as] = await Promise.allSettled([
      api.getWorld(worldId),
      api.events(worldId, "offscreen", 30),
      api.ui(worldId),
      api.assets(worldId),
    ]);
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
    if (as.status === "fulfilled") setAssets((old) => mergeById(old, as.value));
  }, [worldId]);

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
        if (live) setLoadError((e as Error).message);
      } finally {
        if (live) setLoaded(true);
      }
    })();
    return () => {
      live = false;
      abort.current?.abort();
    };
  }, [worldId, refreshSide]);

  // Opening illustration/voice may be produced asynchronously after confirm: poll briefly.
  const hasImage = assets.some((a) => a.type === "image");
  useEffect(() => {
    if (!loaded || hasImage) return;
    let n = 0;
    const t = setInterval(() => {
      if (++n > 12) return clearInterval(t);
      api
        .assets(worldId)
        .then((as) => as.length && setAssets((old) => mergeById(old, as)))
        .catch(() => {});
    }, 2500);
    return () => clearInterval(t);
  }, [loaded, hasImage, worldId]);

  // Opening is a key scene (F5): if the backend produced its illustration but no narration audio,
  // ask once for TTS of the opening (server caches by text hash, so reloads don't re-synthesise).
  const openingVoiceAsked = useRef(false);
  const hasOpeningTurn = turns.some((t) => t.index === 0);
  const openingImage = assets.some((a) => a.type === "image" && !a.turn_id);
  const openingAudio = assets.some((a) => a.type === "audio" && !a.turn_id);
  useEffect(() => {
    if (!loaded || !world || hasOpeningTurn || openingAudio || !openingImage || openingVoiceAsked.current)
      return;
    const text = (world.opening_scene || "").trim();
    if (!text) return;
    const t = setTimeout(() => {
      openingVoiceAsked.current = true;
      api
        .tts(worldId, { text: text.slice(0, 600) })
        .then((a) => setAssets((old) => mergeById(old, [{ ...a, turn_id: null }])))
        .catch(() => {});
    }, 1500);
    return () => clearTimeout(t);
  }, [loaded, world, hasOpeningTurn, openingAudio, openingImage, worldId]);

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
      let newOptions: Option[] | null = null;
      try {
        await streamSSE(
          path,
          body,
          (event, data) => {
            const d = (data ?? {}) as Record<string, unknown>;
            switch (event) {
              case "progress":
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
                setAssets((old) => mergeById(old, [d as unknown as Asset]));
                break;
              case "safety": {
                const s = d as unknown as SafetyResult;
                setSafety(s);
                if (s.blocked) blocked = true;
                break;
              }
              case "error":
                setError({ message: String(d.message ?? "生成失败"), retryable: d.retryable !== false });
                break;
              case "done": {
                gotDone = true;
                if (d.blocked) {
                  blocked = true;
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
        if (!ctrl.signal.aborted) setError({ message: (e as Error).message || "网络异常", retryable: true });
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
        }
      } else {
        // nothing was committed: drop the partial narration, the pending body stays for retry.
        target.current = "";
        setTargetText("");
        setLive(null);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [worldId, refreshSide],
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
