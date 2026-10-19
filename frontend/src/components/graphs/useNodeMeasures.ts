/**
 * Controlled React Flow nodes are rebuilt from props on every render (live world updates, selection),
 * which would drop the `measured` size React Flow recorded — it then keeps those nodes hidden because
 * an unchanged size never re-triggers its ResizeObserver. Keep measured sizes (and drag positions) in
 * state and merge them back into each freshly built node.
 */
import { useCallback, useState } from "react";
import type { Node, NodeChange, XYPosition } from "@xyflow/react";

type Dims = { width: number; height: number };

export function useNodeMeasures(keepDrag: boolean) {
  const [dims, setDims] = useState<Record<string, Dims>>({});
  const [moved, setMoved] = useState<Record<string, XYPosition>>({});
  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const d: Record<string, Dims> = {};
      const p: Record<string, XYPosition> = {};
      for (const c of changes) {
        if (c.type === "dimensions" && c.dimensions) d[c.id] = c.dimensions;
        if (keepDrag && c.type === "position" && c.position) p[c.id] = c.position;
      }
      if (Object.keys(d).length) setDims((o) => ({ ...o, ...d }));
      if (Object.keys(p).length) setMoved((o) => ({ ...o, ...p }));
    },
    [keepDrag],
  );
  const merge = useCallback(
    <T extends Node>(n: T): T => ({
      ...n,
      measured: dims[n.id] ?? n.measured,
      position: moved[n.id] ?? n.position,
    }),
    [dims, moved],
  );
  return { onNodesChange, merge };
}
