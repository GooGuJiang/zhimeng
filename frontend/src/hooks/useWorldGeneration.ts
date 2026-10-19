"use client";
import { errorText } from "@/lib/api";
/**
 * F1 / F10: drives a world-generation SSE stream (generate, education, regenerate) and exposes
 * progress, the draft text the LLM is writing, safety blocks and the resulting world.
 */
import { useCallback, useRef, useState } from "react";
import { streamSSE } from "@/lib/sse";
import type { Progress, SafetyResult, World } from "@/lib/types";

export const GEN_STAGES = [
  "safety",
  "outline",
  "locations",
  "characters",
  "conflict",
  "persist",
  "memory",
  "done",
];

export interface GenState {
  running: boolean;
  progress: Progress | null;
  draft: string;
  world: World | null;
  safety: SafetyResult | null;
  error: string | null;
}

const initial: GenState = {
  running: false,
  progress: null,
  draft: "",
  world: null,
  safety: null,
  error: null,
};

export function useWorldGeneration() {
  const [state, setState] = useState<GenState>(initial);
  const abort = useRef<AbortController | null>(null);

  const run = useCallback(
    async (path: string, body: unknown): Promise<{ world: World | null; worldId: string | null }> => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      setState({
        ...initial,
        running: true,
        progress: { stage: "safety", message: "正在审视你的灵感", pct: 2 },
      });
      let world: World | null = null;
      let worldId: string | null = null;
      try {
        await streamSSE(
          path,
          body,
          (event, data) => {
            const d = data as Record<string, unknown>;
            switch (event) {
              case "progress":
                setState((s) => ({ ...s, progress: d as unknown as Progress }));
                break;
              case "token":
                setState((s) => ({ ...s, draft: (s.draft + String(d.text ?? "")).slice(-600) }));
                break;
              case "world":
                world = d as unknown as World;
                worldId = world.id;
                setState((s) => ({ ...s, world }));
                break;
              case "safety":
                setState((s) => ({ ...s, safety: d as unknown as SafetyResult }));
                break;
              case "error":
                setState((s) => ({ ...s, error: String(d.message ?? "生成失败，请重试") }));
                break;
              case "done":
                if (typeof d?.world_id === "string") worldId = d.world_id;
                // v1.2: done.detail_status is authoritative for the (first) world payload.
                if (world && typeof d?.detail_status === "string") {
                  world = { ...(world as World), detail_status: d.detail_status as World["detail_status"] };
                  setState((s) => ({ ...s, world }));
                }
                break;
            }
          },
          ctrl.signal,
        );
      } catch (e) {
        if (!ctrl.signal.aborted) setState((s) => ({ ...s, error: errorText(e) }));
      } finally {
        setState((s) => ({ ...s, running: false }));
      }
      return { world, worldId };
    },
    [],
  );

  const cancel = useCallback(() => {
    abort.current?.abort();
    setState((s) => ({ ...s, running: false }));
  }, []);

  return { ...state, run, cancel };
}
