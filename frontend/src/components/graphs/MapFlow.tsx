"use client";
/** 世界地图 — React Flow canvas; authored coordinates as anchors, collide force de-overlaps places. */
import { memo, useMemo } from "react";
import { useNodeMeasures } from "./useNodeMeasures";
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  Handle,
  Position,
  ReactFlow,
  getStraightPath,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { mapLayout } from "./layout";

export type MapLoc = {
  id: string;
  name: string;
  x: number;
  y: number;
  description?: string;
  characters?: string[];
};

type PlaceData = { name: string; here: boolean; on: boolean; near: boolean; people: number };
type RoadData = { live: boolean };

const centre = { left: "50%", top: 9, opacity: 0, width: 1, height: 1, minWidth: 0, minHeight: 0, border: 0 };

const PlaceNode = memo(function PlaceNode({ data }: NodeProps<Node<PlaceData>>) {
  return (
    <div
      className={`rf-place${data.here ? " here" : ""}${data.on ? " on" : ""}${data.near ? " near" : ""}`}
      data-testid="map-node"
      data-here={data.here || undefined}
    >
      <Handle type="target" position={Position.Top} style={centre} isConnectable={false} />
      <Handle type="source" position={Position.Top} style={centre} isConnectable={false} />
      <span className="rf-pin" aria-hidden />
      <span className="rf-place-name">
        {data.name}
        {data.people ? <i>{data.people}</i> : null}
      </span>
      {data.here ? <span className="rf-here">你在这里</span> : null}
    </div>
  );
});

function RoadEdge({ id, sourceX, sourceY, targetX, targetY, data }: EdgeProps<Edge<RoadData>>) {
  const [path] = getStraightPath({ sourceX, sourceY, targetX, targetY });
  return <BaseEdge id={id} path={path} className={`rf-road${data?.live ? " live" : ""}`} />;
}

const nodeTypes = { place: PlaceNode };
const edgeTypes = { road: RoadEdge };

export default function MapFlow({
  locations,
  edges,
  current,
  selected,
  onSelect,
  height = 300,
}: {
  locations: MapLoc[];
  edges: { source: string; target: string }[];
  current?: string;
  selected: string | null;
  onSelect: (id: string | null) => void;
  height?: number;
}) {
  const topo = locations.map((l) => `${l.id}@${l.x},${l.y}`).join(";");
  const pos = useMemo(
    () => mapLayout(locations),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- layout only depends on topology/coords
    [topo],
  );
  const neighbours = new Set<string>();
  for (const e of edges) {
    if (e.source === current) neighbours.add(e.target);
    if (e.target === current) neighbours.add(e.source);
  }
  const m = useNodeMeasures(false);
  const rfNodes: Node<PlaceData>[] = locations
    .map((l) => {
      const p = pos.get(l.id) ?? { x: 0, y: 0 };
      return {
        id: l.id,
        type: "place",
        position: { x: p.x - 50, y: p.y - 9 },
        data: {
          name: l.name,
          here: l.id === current,
          on: l.id === selected,
          near: neighbours.has(l.id),
          people: l.characters?.length ?? 0,
        },
        draggable: false,
        selectable: false,
        ariaLabel: `${l.name}${l.id === current ? "（当前位置）" : ""}`,
      };
    })
    .map(m.merge);
  const ids = new Set(locations.map((l) => l.id));
  const rfEdges: Edge<RoadData>[] = edges
    .filter((e) => ids.has(e.source) && ids.has(e.target))
    .map((e, i) => ({
      id: `r${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      type: "road",
      data: { live: e.source === current || e.target === current },
    }));

  return (
    <div className="rf-wrap rf-map" style={{ height }} data-testid="map-flow">
      <ReactFlow
        key={locations.map((l) => l.id).join(",")}
        nodes={rfNodes}
        onNodesChange={m.onNodesChange}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.12, maxZoom: 1.2 }}
        minZoom={0.3}
        maxZoom={2.5}
        zoomOnScroll={false}
        preventScrolling={false}
        nodesConnectable={false}
        elementsSelectable={false}
        onNodeClick={(_, n) => onSelect(selected === n.id ? null : n.id)}
        onPaneClick={() => onSelect(null)}
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} className="rf-bg" />
        <Controls showInteractive={false} position="top-right" />
      </ReactFlow>
    </div>
  );
}
