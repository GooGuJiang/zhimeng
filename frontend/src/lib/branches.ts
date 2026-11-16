/**
 * Character-branch helpers (评审改版 2026-11-16).
 *
 * The play page already had option buttons + free input (`Option`, `GET /options`, SSE `done.options`).
 * What was missing: a short consequence hint on every choice, and a multi-line 剧情脉络 with the
 * ability to return to a point and take another path.
 *
 * Contract (FRONTEND_REQUESTS.md §5): GET /worlds/{id}/branches, POST /worlds/{id}/branches/rewind.
 * Until the backend ships those, we build a single-line tree from GET /turns and hide "另选".
 */
import type { Option, Turn } from "./types";

export const OPENING_NODE_ID = "opening";

export interface BranchNode {
  id: string;
  parent_id: string | null;
  /** The committed turn this node represents; null at the opening. */
  turn_id: string | null;
  index: number;
  chapter: number;
  /** The action that arrived here; null at the opening. */
  action: string | null;
  choice_id: string | null;
  /** Short narration excerpt for the tree. Never an internal id. */
  summary: string;
  line_id: string;
  current?: boolean;
}

export interface BranchLine {
  id: string;
  leaf_id: string;
  current: boolean;
}

export interface BranchTree {
  current_node_id: string;
  nodes: BranchNode[];
  lines: BranchLine[];
}

export interface BranchRewind {
  current_node_id: string;
  options: Option[];
  world?: unknown;
}

const HINT_RULES: [RegExp, string][] = [
  [/追问|询问|请教|打听/, "也许能听到尚未公开的消息"],
  [/调查|查看|搜查|翻看|探查/, "可能发现被忽略的线索"],
  [/前往|去往|走向|去\S|走到/, "场景会转到另一个地方"],
  [/观望|等待|静观|按兵/, "先按兵不动，看看局势变化"],
  [/商量|求助|找个|寻访/, "或许能得到一个建议"],
  [/整理|理一理|回顾/, "把已知的事情再理一遍"],
  [/躲|避开|离开|撤退/, "暂时离开眼前的危险"],
  [/跟|跟上|同行/, "跟着对方，走一条未知的路"],
  [/说服|劝/, "对方未必会答应"],
  [/打开|推开|进入/, "门后的情况还不确定"],
];

/** A short consequence teaser when the server omitted `hint`. */
export function fallbackHint(text: string): string {
  const t = text.trim();
  for (const [re, hint] of HINT_RULES) if (re.test(t)) return hint;
  return "剧情将沿这条选择继续";
}

export function withHints(options: Option[]): Option[] {
  return options.map((o) => ({ ...o, hint: o.hint?.trim() || fallbackHint(o.text) }));
}

export function clipSummary(text: string, max = 36): string {
  const t = text.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

export function treeFromTurns(turns: Turn[]): BranchTree {
  const sorted = [...turns].filter((t) => t.index > 0).sort((a, b) => a.index - b.index);
  const line = "line_main";
  const nodes: BranchNode[] = [
    {
      id: OPENING_NODE_ID,
      parent_id: null,
      turn_id: null,
      index: 0,
      chapter: 1,
      action: null,
      choice_id: null,
      summary: "故事从这里开始",
      line_id: line,
    },
  ];
  let parent = OPENING_NODE_ID;
  for (const t of sorted) {
    nodes.push({
      id: t.id,
      parent_id: parent,
      turn_id: t.id,
      index: t.index,
      chapter: t.chapter,
      action: t.action || null,
      choice_id: null,
      summary: clipSummary(t.narration),
      line_id: line,
    });
    parent = t.id;
  }
  const current = nodes[nodes.length - 1]!.id;
  for (const n of nodes) n.current = n.id === current;
  return {
    current_node_id: current,
    nodes,
    lines: [{ id: line, leaf_id: current, current: true }],
  };
}

export function parseBranchTree(raw: unknown): BranchTree | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Partial<BranchTree>;
  if (!Array.isArray(r.nodes) || !r.current_node_id) return null;
  const nodes = r.nodes
    .filter((n) => n && typeof n.id === "string")
    .map((n) => ({
      id: n.id,
      parent_id: n.parent_id ?? null,
      turn_id: n.turn_id ?? null,
      index: Number(n.index) || 0,
      chapter: Number(n.chapter) || 1,
      action: n.action ?? null,
      choice_id: n.choice_id ?? null,
      summary: String(n.summary ?? ""),
      line_id: String(n.line_id ?? "line_main"),
      current: Boolean(n.current) || n.id === r.current_node_id,
    }));
  if (!nodes.length) return null;
  const lines = Array.isArray(r.lines)
    ? r.lines.filter((l) => l && l.id && l.leaf_id).map((l) => ({ id: l.id, leaf_id: l.leaf_id, current: Boolean(l.current) }))
    : [{ id: "line_main", leaf_id: r.current_node_id, current: true }];
  return { current_node_id: r.current_node_id, nodes, lines };
}

export function childrenOf(nodes: BranchNode[], parentId: string | null): BranchNode[] {
  return nodes.filter((n) => n.parent_id === parentId);
}

/** Depth-first order, siblings keep their original order (first walked line stays left/top). */
export function walkTree(nodes: BranchNode[]): { node: BranchNode; depth: number }[] {
  const out: { node: BranchNode; depth: number }[] = [];
  const go = (id: string | null, depth: number) => {
    for (const n of childrenOf(nodes, id)) {
      out.push({ node: n, depth });
      go(n.id, depth + 1);
    }
  };
  const roots = nodes.filter((n) => !n.parent_id);
  if (roots.length) {
    for (const r of roots) {
      out.push({ node: r, depth: 0 });
      go(r.id, 1);
    }
  } else go(null, 0);
  return out;
}

export function lineCount(tree: BranchTree): number {
  return Math.max(tree.lines.length, new Set(tree.nodes.map((n) => n.line_id)).size);
}
