/** Graph layout helpers (d3-force, run synchronously so the result is deterministic and SSR-free). */
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
} from "d3-force";
import type { SimulationLinkDatum, SimulationNodeDatum } from "d3-force";

type N = SimulationNodeDatum & { id: string };

/** Force-directed layout for the relationship graph; the player (if any) is pinned in the centre. */
export function forceLayout(
  ids: string[],
  links: { source: string; target: string; weight?: number }[],
  pinned?: string | null,
): Map<string, { x: number; y: number }> {
  const nodes: N[] = ids.map((id) => (id === pinned ? { id, fx: 0, fy: 0 } : { id }));
  const known = new Set(ids);
  const ls: SimulationLinkDatum<N>[] = links
    .filter((l) => known.has(l.source) && known.has(l.target) && l.source !== l.target)
    .map((l) => ({ source: l.source, target: l.target }));
  const sim = forceSimulation(nodes)
    .force(
      "link",
      forceLink<N, SimulationLinkDatum<N>>(ls)
        .id((d) => d.id)
        .distance(150)
        .strength(0.35),
    )
    .force("charge", forceManyBody().strength(-700))
    .force("collide", forceCollide(62))
    .force("x", forceX(0).strength(0.04))
    .force("y", forceY(0).strength(0.06))
    .stop();
  if (!pinned) sim.force("center", forceCenter(0, 0));
  for (let i = 0; i < 320; i++) sim.tick();
  return new Map(nodes.map((n) => [n.id, { x: n.x ?? 0, y: n.y ?? 0 }]));
}

/**
 * World map: keep the authored 0..100 coordinates as anchors, but let a collide force push apart
 * places that the generator stacked on top of each other (common with LLM output / fallback data).
 */
export function mapLayout(
  locs: { id: string; x: number; y: number }[],
  width = 640,
  height = 440,
): Map<string, { x: number; y: number }> {
  const clamp = (v: number) => Math.max(0, Math.min(100, Number.isFinite(v) ? v : 50));
  const nodes = locs.map((l) => ({
    id: l.id,
    ax: (clamp(l.x) / 100) * width,
    ay: (clamp(l.y) / 100) * height,
  })) as (N & { ax: number; ay: number })[];
  nodes.forEach((n) => {
    n.x = n.ax;
    n.y = n.ay;
  });
  const sim = forceSimulation(nodes)
    .force("x", forceX<N & { ax: number }>((d) => d.ax).strength(0.5))
    .force("y", forceY<N & { ay: number }>((d) => d.ay).strength(0.5))
    .force("collide", forceCollide(58))
    .stop();
  for (let i = 0; i < 200; i++) sim.tick();
  return new Map(nodes.map((n) => [n.id, { x: n.x ?? n.ax, y: n.y ?? n.ay }]));
}

const ROLE_PALETTE = ["azure", "rose", "jade", "plum", "teal", "ochre"] as const;
export type RoleTone = (typeof ROLE_PALETTE)[number];

/** Stable colour family per role/faction keyword (same role → same colour across views). */
export function roleTone(role?: string): RoleTone {
  const r = (role ?? "").trim();
  if (!r) return "ochre";
  const rules: [RegExp, RoleTone][] = [
    [/巡捕|警|探|官|兵|军|侍卫|捕快/, "azure"],
    [/帮|匪|盗|杀手|刺客|黑|暗/, "rose"],
    [/医|师|学|先生|教|书|记者|报/, "jade"],
    [/商|老板|掌柜|买办|富/, "ochre"],
    [/舞|歌|伶|戏|艺/, "plum"],
  ];
  for (const [re, t] of rules) if (re.test(r)) return t;
  let h = 0;
  for (const ch of r) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return ROLE_PALETTE[h % ROLE_PALETTE.length];
}

export function affinityKind(a = 0): "pos" | "neg" | "neutral" {
  if (a >= 30) return "pos";
  if (a <= -30) return "neg";
  return "neutral";
}
