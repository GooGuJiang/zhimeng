/**
 * UIComponent (backend JSON spec, API.md §F6) → OpenUI Lang 1.0 program.
 *
 * The backend decides *which* panels exist, their priority/size and their data from the current
 * plot; we express each one as an OpenUI program so a single renderer (OpenUI <Renderer>) draws
 * every generative panel. If a component carries an `openui` program that parses against our
 * library, that program wins (LLM-authored layout); otherwise the deterministic compiler below runs.
 */
import type { UIComponent, Option, WorldEvent, KnowledgeCard } from "@/lib/types";

/** OpenUI Lang literals are JSON-compatible: strings, numbers, arrays, objects. */
const lit = (v: unknown) => JSON.stringify(v ?? null);

type Anyish = Record<string, unknown>;
const arr = <T = Anyish>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
const num = (v: unknown, d = 0) => (typeof v === "number" && Number.isFinite(v) ? v : d);
const str = (v: unknown, d = "") => (typeof v === "string" ? v : v == null ? d : String(v));

const STAT_TONES = ["gold", "azure", "jade", "rose"] as const;

function statusPanel(p: Anyish): string[] {
  const player = (p.player ?? {}) as Anyish;
  const stats = (p.stats ?? {}) as Record<string, number>;
  const lines = [
    `root = Col([head, meters, tags], 3)`,
    `head = Row([Stat("身份", ${lit(str(player.name, "你"))}, ${lit(str(player.role))}), Stat("所在", ${lit(
      str(player.location, "未知"),
    )}), Stat("时辰", ${lit(str(p.time, "—"))}, ${lit(`第${num(p.chapter, 1)}章 · 第${num(p.turn, 0)}回`)})], 4, "between")`,
  ];
  const meters = [`Meter("体力", ${num(player.hp, 100)}, 100, "rose")`];
  Object.entries(stats)
    .slice(0, 5)
    .forEach(([k, v], i) =>
      meters.push(
        `Meter(${lit(k)}, ${num(v)}, ${num(v) > 100 ? Math.ceil(num(v) / 50) * 50 : 100}, "${STAT_TONES[i % 4]}")`,
      ),
    );
  lines.push(`meters = Col([${meters.join(", ")}], 2)`);
  const tags = arr<string>(p.tags).slice(0, 8);
  const moodTag = player.mood ? [`Badge(${lit("心境 · " + str(player.mood))}, "azure")`] : [];
  lines.push(
    `tags = Row([${[...moodTag, ...tags.map((t) => `Badge(${lit(str(t))}, "muted")`)].join(", ")}], 2)`,
  );
  return lines;
}

function relationGraph(p: Anyish): string[] {
  const nodes = arr(p.nodes).map((n) => ({
    id: str(n.id),
    label: str(n.label ?? n.name),
    role: str(n.role),
    mood: str(n.mood),
    emoji: str(n.emoji),
    is_player: !!n.is_player,
  }));
  const edges = arr(p.edges).map((e) => ({
    source: str(e.source),
    target: str(e.target),
    type: str(e.type),
    affinity: num(e.affinity),
  }));
  return [`root = Col([graph], 2)`, `graph = RelationGraph(${lit(nodes)}, ${lit(edges)})`];
}

function inventory(p: Anyish): string[] {
  const items = arr(p.items).map((i) => ({
    id: str(i.id),
    name: str(i.name),
    description: str(i.description),
    quantity: num(i.quantity, 1),
  }));
  return [`root = Col([bag], 2)`, `bag = Inventory(${lit(items)})`];
}

function map(p: Anyish): string[] {
  const locations = arr(p.locations).map((l) => ({
    id: str(l.id),
    name: str(l.name),
    x: num(l.x, 50),
    y: num(l.y, 50),
    description: str(l.description),
    characters: arr<string>(l.characters).map((c) => str(c)),
  }));
  const edges = arr(p.edges).map((e) => ({ source: str(e.source), target: str(e.target) }));
  return [
    `root = Col([m], 2)`,
    `m = WorldMap(${lit(locations)}, ${lit(edges)}, ${lit(str(p.current_location_id))})`,
  ];
}

function eventFeed(p: Anyish): string[] {
  const events = arr<WorldEvent>(p.events).slice(0, 8);
  if (!events.length) return [`root = Col([Text("暂时风平浪静。", "muted")])`];
  return [
    `root = Col([${events.map((_, i) => `e${i}`).join(", ")}], 2)`,
    ...events.map(
      (e, i) =>
        `e${i} = EventLine(${lit(str(e.summary))}, ${lit(str(e.in_world_time))}, ${lit(str(e.type))}, ${lit(
          str(e.impact),
        )})`,
    ),
  ];
}

function knowledge(p: Anyish): string[] {
  const cards = arr<KnowledgeCard>(p.cards);
  if (!cards.length) return [`root = Col([Text("继续探索，解锁知识卡片。", "muted")])`];
  return [
    `root = Col([g])`,
    `g = Grid([${cards.map((_, i) => `k${i}`).join(", ")}], 2)`,
    ...cards.map(
      (c, i) => `k${i} = KnowledgeCard(${lit(str(c.title))}, ${lit(str(c.content))}, ${lit(str(c.source))})`,
    ),
  ];
}

function choices(p: Anyish): string[] {
  const options = arr<Option>(p.options).map((o) => ({
    id: str(o.id),
    text: str(o.text),
    hint: str(o.hint),
  }));
  return [`root = Col([c])`, `c = Choices(${lit(options)})`];
}

export function compileComponent(c: UIComponent): string {
  const p = (c.props ?? {}) as Anyish;
  let lines: string[];
  switch (c.type) {
    case "status_panel":
      lines = statusPanel(p);
      break;
    case "relationship_graph":
      lines = relationGraph(p);
      break;
    case "inventory":
      lines = inventory(p);
      break;
    case "map":
      lines = map(p);
      break;
    case "event_feed":
      lines = eventFeed(p);
      break;
    case "knowledge_cards":
      lines = knowledge(p);
      break;
    case "choice_list":
      lines = choices(p);
      break;
    default:
      lines = [`root = Col([Text(${lit(c.title || "未知面板")}, "muted")])`];
  }
  // Backend-provided actions become buttons under the panel.
  const acts = arr(c.actions).filter((a) => a && a.label);
  if (acts.length) {
    const rootExpr = lines[0].replace(/^root = /, "");
    lines[0] = `root = Col([body, acts], 3)`;
    lines.splice(1, 0, `body = ${rootExpr}`);
    const btn = (a: Anyish) => {
      const payload = (a.payload ?? {}) as Anyish;
      const label = str(a.label);
      if (a.kind === "god_inject")
        return `Button(${lit(label)}, @Inject(${lit(str(payload.content, label))}), "ghost")`;
      if (a.kind === "query")
        return `Button(${lit(label)}, @Ask(${lit(str(payload.question, label))}), "ghost")`;
      return `Button(${lit(label)}, @Act(${lit(str(payload.action, label))}), "ghost")`;
    };
    lines.push(`acts = Row([${acts.slice(0, 4).map(btn).join(", ")}], 2)`);
  }
  return lines.join("\n");
}

/** Prefer an LLM-authored program if one was provided; the caller validates it. */
export function programFor(c: UIComponent): { program: string; authored: boolean } {
  if (c.openui && /^\s*root\s*=/m.test(c.openui)) return { program: c.openui, authored: true };
  return { program: compileComponent(c), authored: false };
}
