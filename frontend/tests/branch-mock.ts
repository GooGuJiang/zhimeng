/**
 * In-memory 剧情脉络 for Playwright: GET /branches, POST /branches/rewind, and a turn stream
 * that actually forks when the player picks a different path from an earlier node.
 */
import { sse, type Json, type MockState } from "./mock-api";
import {
  OPENING_NODE_ID,
  clipSummary,
  fallbackHint,
  type BranchLine,
  type BranchNode,
  type BranchTree,
} from "../src/lib/branches";

export interface BranchEngine {
  tree: BranchTree;
  turnsById: Map<string, Json>;
  optionsAt: Map<string, Json[]>;
  currentOptions: Json[];
}

const DEMO_PATHS: Record<string, { narration: string; next: Json[] }> = {
  opt_1: {
    narration:
      "你压低声音，向顾长庚追问细节。他左右看了看，才说：“铁门后面不是普通货物。有人用巡捕的名义运过两箱东西。”灯火摇晃，你记下了这个名字。",
    next: [
      { id: "opt_a1", text: "夜里去铁门附近守候", hint: "可能会撞见不该看见的人" },
      { id: "opt_a2", text: "先去报馆核对那两箱货", hint: "也许能从旧新闻里找到出处" },
      { id: "opt_a3", text: "暂时把这条线按住", hint: "先不打草惊蛇" },
    ],
  },
  opt_2: {
    narration:
      "你绕到仓库铁门前。锁是新换的，门缝里透出一丝机油气味。脚下的泥里有浅浅的轮印，一直伸向江边。你意识到：这里最近有车来过。",
    next: [
      { id: "opt_b1", text: "沿着轮印走到江边", hint: "可能找到运货的船" },
      { id: "opt_b2", text: "想办法弄清楚这把锁", hint: "也许能知道是谁换的" },
      { id: "opt_b3", text: "先离开，免得被人看见", hint: "安全，但线索会冷掉" },
    ],
  },
  opt_3: {
    narration:
      "你走进法租界巡捕房。值班的巡捕翻着册子，并不热心。窗外电车驶过，他随口说：“最近江边的仓库报案不少，可没有一桩立了案。”你只好记下这句空话。",
    next: [
      { id: "opt_c1", text: "再问一问报案的人是谁", hint: "可能得到一个名字" },
      { id: "opt_c2", text: "改去码头打听", hint: "线索或许在巡捕管不到的地方" },
      { id: "opt_c3", text: "先回家把今天的事写下", hint: "把已知的事情再理一遍" },
    ],
  },
};

function hintify(opts: Json[]): Json[] {
  return opts.map((o) => ({
    ...o,
    hint: String(o.hint || "").trim() || fallbackHint(String(o.text || "")),
  }));
}

export function bootBranchEngine(st: MockState, opening: Json[]): BranchEngine {
  const opts = hintify(opening);
  const turnsById = new Map<string, Json>();
  for (const t of st.turns) turnsById.set(String(t.id), t);
  const sorted = [...st.turns].sort((a, b) => Number(a.index) - Number(b.index));
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
      line_id: "line_main",
    },
  ];
  const optionsAt = new Map<string, Json[]>();
  optionsAt.set(OPENING_NODE_ID, opts);
  let parent = OPENING_NODE_ID;
  const line = "line_main";
  for (const t of sorted) {
    const id = String(t.id);
    nodes.push({
      id,
      parent_id: parent,
      turn_id: id,
      index: Number(t.index),
      chapter: Number(t.chapter) || 1,
      action: String(t.action || ""),
      choice_id: null,
      summary: clipSummary(String(t.narration || "")),
      line_id: line,
    });
    optionsAt.set(id, hintify((t.options as Json[]) || opts));
    parent = id;
  }
  const current = nodes[nodes.length - 1]!.id;
  for (const n of nodes) n.current = n.id === current;
  const lines: BranchLine[] = [{ id: line, leaf_id: current, current: true }];
  const tree: BranchTree = { current_node_id: current, nodes, lines };
  const currentOptions = optionsAt.get(current) ?? opts;
  return { tree, turnsById, optionsAt, currentOptions };
}

export function handleBranchRoute(eng: BranchEngine, st: MockState, method: string, path: string, body: Json | null): unknown | "SSE" | undefined {
  const wid = String(st.world.id);
  const base = `/worlds/${wid}`;
  if (path === `${base}/branches` && method === "GET") return snapshot(eng);
  if (path === `${base}/branches/rewind` && method === "POST") {
    const id = String(body?.to_node_id || "");
    const node = eng.tree.nodes.find((n) => n.id === id);
    if (!node) return { $http: true, status: 404, body: { detail: "找不到要回到的那一步", code: "not_found" } };
    setCurrent(eng, id);
    st.turns = lineTurns(eng);
    st.options = { options: eng.currentOptions };
    applyWorldTurn(st, node);
    return {
      current_node_id: id,
      options: eng.currentOptions,
      world: st.world,
    };
  }
  return undefined;
}

export function forkTurnStream(eng: BranchEngine, st: MockState, body: Json): string {
  const action = String(body.action || "").trim();
  const optionId = body.option_id ? String(body.option_id) : null;
  const parentId = eng.tree.current_node_id;
  const parent = eng.tree.nodes.find((n) => n.id === parentId);
  const siblings = eng.tree.nodes.filter((n) => n.parent_id === parentId);
  const newLine = siblings.length > 0;
  const lineId = newLine ? `line_${eng.tree.lines.length + 1}` : (parent?.line_id ?? "line_main");
  const index = (parent?.index ?? 0) + 1;
  const canned = (optionId && DEMO_PATHS[optionId]) || matchPath(action);
  const narration = canned?.narration ?? `你决定：${action}。风从江面上吹来，故事由此转向另一条路。`;
  const next = hintify(canned?.next ?? defaultNext());
  const id = `t_fork_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
  const turn: Json = {
    id,
    world_id: st.world.id,
    index,
    chapter: parent?.chapter ?? 1,
    action,
    narration,
    options: next,
    events: [],
    facts: [],
    asset_ids: [],
    key_scene: false,
    source: "fallback",
    created_at: new Date().toISOString(),
    ai_generated: true,
    ai_label: "",
  };
  eng.turnsById.set(id, turn);
  const node: BranchNode = {
    id,
    parent_id: parentId,
    turn_id: id,
    index,
    chapter: Number(turn.chapter),
    action,
    choice_id: optionId,
    summary: clipSummary(narration),
    line_id: lineId,
    current: true,
  };
  for (const n of eng.tree.nodes) n.current = false;
  eng.tree.nodes.push(node);
  if (newLine) {
    for (const l of eng.tree.lines) l.current = false;
    eng.tree.lines.push({ id: lineId, leaf_id: id, current: true });
  } else {
    const line = eng.tree.lines.find((l) => l.id === lineId);
    if (line) {
      line.leaf_id = id;
      line.current = true;
    } else eng.tree.lines.push({ id: lineId, leaf_id: id, current: true });
  }
  eng.tree.current_node_id = id;
  eng.optionsAt.set(id, next);
  eng.currentOptions = next;
  st.turns = lineTurns(eng);
  st.options = { options: next };
  applyWorldTurn(st, node);
  return sse([
    ["progress", { stage: "write", message: "正在写下这一段", pct: 40, percent: 40 }],
    ["token", { text: narration.slice(0, 20) }],
    ["token", { text: narration.slice(20) }],
    ["options", { options: next }],
    ["done", { turn, state: st.world.state, reset: false }],
  ]);
}

function snapshot(eng: BranchEngine): BranchTree {
  return {
    current_node_id: eng.tree.current_node_id,
    nodes: eng.tree.nodes.map((n) => ({ ...n, current: n.id === eng.tree.current_node_id })),
    lines: eng.tree.lines.map((l) => ({ ...l })),
  };
}

function setCurrent(eng: BranchEngine, id: string) {
  eng.tree.current_node_id = id;
  for (const n of eng.tree.nodes) n.current = n.id === id;
  const node = eng.tree.nodes.find((n) => n.id === id)!;
  for (const l of eng.tree.lines) l.current = l.id === node.line_id;
  eng.currentOptions = eng.optionsAt.get(id) ?? [];
}

function lineTurns(eng: BranchEngine): Json[] {
  const path: string[] = [];
  let id: string | null = eng.tree.current_node_id;
  const byId = new Map(eng.tree.nodes.map((n) => [n.id, n]));
  while (id && id !== OPENING_NODE_ID) {
    path.unshift(id);
    id = byId.get(id)?.parent_id ?? null;
  }
  return path.map((tid) => eng.turnsById.get(tid)).filter(Boolean) as Json[];
}

function applyWorldTurn(st: MockState, node: BranchNode) {
  const state = (st.world.state ?? {}) as Json;
  st.world = { ...st.world, state: { ...state, turn: node.index, chapter: node.chapter }, updated_at: new Date().toISOString() };
}

function matchPath(action: string) {
  for (const [k, v] of Object.entries(DEMO_PATHS)) {
    // canned next options aren't used for matching; the narration keys are option ids.
    if (action.includes(k)) return v;
  }
  // match by known action text
  if (action.includes("追问")) return DEMO_PATHS.opt_1;
  if (action.includes("铁门")) return DEMO_PATHS.opt_2;
  if (action.includes("巡捕")) return DEMO_PATHS.opt_3;
  return undefined;
}

function defaultNext(): Json[] {
  return [
    { id: "opt_x1", text: "顺着刚才的发现再走一步", hint: "剧情将沿这条选择继续" },
    { id: "opt_x2", text: "换一个方向打听", hint: "也许能听到尚未公开的消息" },
    { id: "opt_x3", text: "先停下来想想", hint: "先按兵不动，看看局势变化" },
  ];
}

export { hintify };
