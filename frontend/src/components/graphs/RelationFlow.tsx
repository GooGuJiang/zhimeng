"use client";
/** 人物关系 — React Flow canvas with a d3-force layout (client only; loaded lazily from the OpenUI library). */
import { memo, useMemo } from "react";
import { useNodeMeasures } from "./useNodeMeasures";
import {
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  getStraightPath,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { affinityKind, forceLayout, roleTone, type RoleTone } from "./layout";

export type RelNode = {
  id: string;
  label: string;
  role?: string;
  mood?: string;
  emoji?: string;
  is_player?: boolean;
};
export type RelEdge = { source: string; target: string; type?: string; affinity?: number };

type PersonData = {
  label: string;
  emoji: string;
  role?: string;
  tone: RoleTone;
  me: boolean;
  on: boolean;
  dim: boolean;
};
type TieData = { label: string; affinity: number; hot: boolean; dim: boolean };

const centre = {
  left: "50%",
  top: "50%",
  opacity: 0,
  width: 1,
  height: 1,
  minWidth: 0,
  minHeight: 0,
  border: 0,
};

const PersonNode = memo(function PersonNode({ data }: NodeProps<Node<PersonData>>) {
  return (
    <div
      className={`rf-person tone-${data.tone}${data.me ? " me" : ""}${data.on ? " on" : ""}${data.dim ? " dim" : ""}`}
      data-testid="relation-node"
    >
      <Handle type="target" position={Position.Top} style={centre} isConnectable={false} />
      <Handle type="source" position={Position.Top} style={centre} isConnectable={false} />
      <span className="rf-avatar" aria-hidden>
        {data.emoji}
      </span>
      <span className="rf-name">{data.label}</span>
      {data.role ? <span className="rf-role">{data.me ? "你" : data.role}</span> : null}
    </div>
  );
});

function TieEdge({ id, sourceX, sourceY, targetX, targetY, data, markerEnd }: EdgeProps<Edge<TieData>>) {
  const [path, lx, ly] = getStraightPath({ sourceX, sourceY, targetX, targetY });
  const k = affinityKind(data?.affinity);
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        className={`rf-tie k-${k}${data?.hot ? " hot" : ""}${data?.dim ? " dim" : ""}`}
        style={{ strokeWidth: 1.2 + Math.abs(data?.affinity ?? 0) / 40 }}
      />
      {data?.label ? (
        <EdgeLabelRenderer>
          <div
            className={`rf-tie-label k-${k}${data.hot ? " hot" : ""}${data.dim ? " dim" : ""}`}
            style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}
          >
            {data.label}
            <b>
              {data.affinity > 0 ? "+" : ""}
              {data.affinity}
            </b>
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

const nodeTypes = { person: PersonNode };
const edgeTypes = { tie: TieEdge };

export default function RelationFlow({
  nodes,
  edges,
  selected,
  onSelect,
  height = 300,
}: {
  nodes: RelNode[];
  edges: RelEdge[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  height?: number;
}) {
  // merge A→B and B→A into one tie so the canvas stays readable
  const ties = useMemo(() => {
    const m = new Map<
      string,
      { source: string; target: string; labels: string[]; aff: number[]; both: boolean }
    >();
    for (const e of edges) {
      if (!e.source || !e.target || e.source === e.target) continue;
      const k = [e.source, e.target].sort().join("|");
      const t = m.get(k);
      if (t) {
        if (t.source !== e.source) t.both = true;
        if (e.type && !t.labels.includes(e.type)) t.labels.push(e.type);
        t.aff.push(e.affinity ?? 0);
      } else
        m.set(k, {
          source: e.source,
          target: e.target,
          labels: e.type ? [e.type] : [],
          aff: [e.affinity ?? 0],
          both: false,
        });
    }
    return [...m.entries()].map(([k, t]) => ({
      id: k,
      ...t,
      affinity: Math.round(t.aff.reduce((a, b) => a + b, 0) / t.aff.length),
    }));
  }, [edges]);

  const player = nodes.find((n) => n.is_player)?.id ?? null;
  const topo = nodes.map((n) => n.id).join(",") + "#" + ties.map((t) => t.id).join(",");
  const pos = useMemo(
    () =>
      forceLayout(
        nodes.map((n) => n.id),
        ties,
        player,
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- layout only depends on topology
    [topo],
  );
  const related = useMemo(() => {
    const s = new Set<string>();
    if (selected)
      for (const t of ties) if (t.source === selected || t.target === selected) s.add(t.source).add(t.target);
    return s;
  }, [selected, ties]);

  const m = useNodeMeasures(true);
  const rfNodes: Node<PersonData>[] = nodes
    .map((n) => {
      const p = pos.get(n.id) ?? { x: 0, y: 0 };
      return {
        id: n.id,
        type: "person",
        position: { x: p.x - 40, y: p.y - 34 },
        data: {
          label: n.label,
          emoji: n.emoji || n.label.slice(0, 1),
          role: n.role,
          tone: n.is_player ? "ochre" : roleTone(n.role),
          me: !!n.is_player,
          on: selected === n.id,
          dim: !!selected && !related.has(n.id) && selected !== n.id,
        },
        draggable: true,
        selectable: false,
        ariaLabel: `${n.label}${n.role ? `（${n.role}）` : ""}`,
      };
    })
    .map(m.merge);
  const rfEdges: Edge<TieData>[] = ties.map((t) => {
    const hot = !!selected && (t.source === selected || t.target === selected);
    return {
      id: t.id,
      source: t.source,
      target: t.target,
      type: "tie",
      markerEnd: t.both ? undefined : { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      data: { label: t.labels.join(" · "), affinity: t.affinity, hot, dim: !!selected && !hot },
    };
  });

  return (
    <div className="rf-wrap" style={{ height }} data-testid="relation-flow">
      <ReactFlow
        key={topo}
        nodes={rfNodes}
        onNodesChange={m.onNodesChange}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.18, maxZoom: 1.1 }}
        minZoom={0.3}
        maxZoom={2}
        zoomOnScroll={false}
        preventScrolling={false}
        zoomOnDoubleClick
        nodesConnectable={false}
        elementsSelectable={false}
        onNodeClick={(_, n) => onSelect(selected === n.id ? null : n.id)}
        onPaneClick={() => onSelect(null)}
      >
        <Controls showInteractive={false} position="top-right" />
      </ReactFlow>
    </div>
  );
}
