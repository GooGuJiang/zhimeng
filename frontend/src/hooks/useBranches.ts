"use client";
/**
 * Loads the 剧情脉络 tree. When GET /branches is 404 (backend not ready), we draw a single line
 * from the turns already on the play page and report `supported: false` so "另选" stays hidden.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, errorText } from "@/lib/api";
import { parseBranchTree, treeFromTurns, type BranchTree } from "@/lib/branches";
import type { Option, Turn, World } from "@/lib/types";

export function useBranches(worldId: string, turns: Turn[], ready: boolean) {
  const [remote, setRemote] = useState<BranchTree | null>(null);
  const [supported, setSupported] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rewinding, setRewinding] = useState(false);
  const seq = useRef(0);
  const missingFor = useRef<string | null>(null);
  const turnKey = useMemo(() => turns.map((t) => t.id).join(","), [turns]);

  const refresh = useCallback(
    async (force = false) => {
      if (!worldId) return;
      if (!force && missingFor.current === worldId) return;
      const n = ++seq.current;
      setLoading(true);
      try {
        const raw = await api.branches(worldId);
        if (n !== seq.current) return;
        const parsed = parseBranchTree(raw);
        if (parsed) {
          missingFor.current = null;
          setRemote(parsed);
          setSupported(true);
          setError(null);
        } else {
          missingFor.current = worldId;
          setRemote(null);
          setSupported(false);
          setError(null);
        }
      } catch (e) {
        if (n !== seq.current) return;
        const absent = e instanceof ApiError && (e.status === 404 || e.status === 405);
        missingFor.current = absent ? worldId : null;
        setRemote(null);
        setSupported(false);
        setError(absent ? null : errorText(e));
      } finally {
        if (n === seq.current) setLoading(false);
      }
    },
    [worldId],
  );

  useEffect(() => {
    if (!ready || !worldId) return;
    if (missingFor.current === worldId) return;
    let live = true;
    void Promise.resolve().then(() => {
      if (live) void refresh();
    });
    return () => {
      live = false;
    };
  }, [ready, worldId, turnKey, refresh]);

  const tree = supported && remote ? remote : treeFromTurns(turns);

  const rewind = useCallback(
    async (to_node_id: string): Promise<{ options?: Option[]; world?: World } | null> => {
      setRewinding(true);
      setError(null);
      try {
        const out = await api.rewindBranch(worldId, to_node_id);
        await refresh(true);
        return { options: out.options, world: out.world as World | undefined };
      } catch (e) {
        setError(errorText(e));
        return null;
      } finally {
        setRewinding(false);
      }
    },
    [worldId, refresh],
  );

  return { tree, supported, loading, error, rewinding, refresh, rewind, clearError: () => setError(null) };
}
