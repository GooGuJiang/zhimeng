"use client";
/**
 * 织梦 generative-UI component library for OpenUI (`@openuidev/react-lang`).
 *
 * The backend (or an LLM "UI agent") describes panels in OpenUI Lang 1.0; <Renderer> parses the
 * (possibly streaming) program and renders it with these components. Layout is not fixed here:
 * primitives (Col/Row/Grid/Panel/...) are arranged by the program, and narrative widgets
 * (Meter, RelationGraph, WorldMap, Inventory, EventLine, KnowledgeCard) are interactive.
 *
 * Interactions leave the generated UI as OpenUI actions:
 *  - @Act("前往码头")  → advance the story with that action (POST /turns)
 *  - @Ask("…")         → query world memory
 *  - @Inject("…")      → god-view event injection
 *  - @ToAssistant(msg) → treated like @Act
 */
import { Markdown } from "@/components/Markdown";
import { MapCanvas, RelationCanvas } from "@/components/graphs";
import {
  action,
  createLibrary,
  defineAction,
  defineComponent,
  useIsStreaming,
  useTriggerAction,
} from "@openuidev/react-lang";
import { useMemo, useState, type ReactNode } from "react";
import { z } from "zod/v4";

const tone = z.enum(["ink", "muted", "gold", "rose", "jade", "azure", "danger"]);
type Tone = z.infer<typeof tone>;
const children = z.array(z.any());

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

/** Build a plan that runs our custom @Act action from inside a component. */
const actPlan = (text: string) => ({ steps: [{ type: "custom_action", name: "Act", params: { text } }] });
type Plan = Parameters<ReturnType<typeof useTriggerAction>>[2];

function useAct() {
  const trigger = useTriggerAction();
  const streaming = useIsStreaming();
  return {
    streaming,
    act: (text: string) => void trigger(text, undefined, actPlan(text) as unknown as Plan),
  };
}

// ---------- actions ----------
export const Act = defineAction({
  name: "Act",
  description: 'Advance the story: the player performs this action, e.g. @Act("去码头找线人").',
  params: z.object({ text: z.string() }),
});
export const Ask = defineAction({
  name: "Ask",
  description: 'Ask the world memory a question about past events, e.g. @Ask("线人叫什么名字？").',
  params: z.object({ question: z.string() }),
});
export const Inject = defineAction({
  name: "Inject",
  description: 'God view: inject a world event, e.g. @Inject("码头突发大火").',
  params: z.object({ content: z.string() }),
});

// ---------- layout ----------
export const Col = defineComponent({
  name: "Col",
  description: "Vertical stack. gap counts 4px steps (default 3).",
  props: z.object({ children, gap: z.number().optional() }),
  component: ({ props, renderNode }) => (
    <div className="zu-col" style={{ gap: (props.gap ?? 3) * 4 }}>
      {renderNode(props.children)}
    </div>
  ),
});
export const Row = defineComponent({
  name: "Row",
  description: "Horizontal row, wraps on narrow screens.",
  props: z.object({
    children,
    gap: z.number().optional(),
    justify: z.enum(["start", "between", "end"]).optional(),
  }),
  component: ({ props, renderNode }) => (
    <div
      className="zu-row"
      style={{
        gap: (props.gap ?? 2) * 4,
        justifyContent:
          props.justify === "between" ? "space-between" : props.justify === "end" ? "flex-end" : "flex-start",
      }}
    >
      {renderNode(props.children)}
    </div>
  ),
});
export const Grid = defineComponent({
  name: "Grid",
  description: "Responsive grid of equal columns (default 2); collapses on phones.",
  props: z.object({ children, columns: z.number().optional() }),
  component: ({ props, renderNode }) => (
    <div
      className="zu-grid"
      style={{ ["--cols" as string]: String(Math.max(1, Math.min(6, props.columns ?? 2))) }}
    >
      {renderNode(props.children)}
    </div>
  ),
});
export const Panel = defineComponent({
  name: "Panel",
  description: "A titled card section. tone tints its accent.",
  props: z.object({
    children,
    title: z.string().optional(),
    tone: tone.optional(),
    icon: z.string().optional(),
  }),
  component: ({ props, renderNode }) => (
    <section className={cx("zu-panel", `t-${props.tone ?? "gold"}`)}>
      {props.title ? (
        <header className="zu-panel-h">
          {props.icon ? <span aria-hidden>{props.icon}</span> : <i className="zu-knot" aria-hidden />}
          <span>{props.title}</span>
        </header>
      ) : null}
      <div className="zu-panel-b">{renderNode(props.children)}</div>
    </section>
  ),
});
export const Divider = defineComponent({
  name: "Divider",
  description: "A thin silk-thread divider.",
  props: z.object({}),
  component: () => <hr className="zu-divider" />,
});

// ---------- text ----------
export const Title = defineComponent({
  name: "Title",
  description: 'Heading. size "sm" | "md" | "lg".',
  props: z.object({ text: z.string(), size: z.enum(["sm", "md", "lg"]).optional() }),
  component: ({ props }) => <h4 className={cx("zu-title", `s-${props.size ?? "md"}`)}>{props.text}</h4>,
});
export const Text = defineComponent({
  name: "Text",
  description: "Body text. tone colors it.",
  props: z.object({ text: z.string(), tone: tone.optional(), size: z.enum(["xs", "sm", "md"]).optional() }),
  component: ({ props }) => (
    <Markdown
      className={cx("zu-text", `c-${props.tone ?? "ink"}`, `s-${props.size ?? "sm"}`)}
      text={props.text}
    />
  ),
});
export const Badge = defineComponent({
  name: "Badge",
  description: "Small tag such as a mood, a status or a time label.",
  props: z.object({ text: z.string(), tone: tone.optional() }),
  component: ({ props }) => (
    <span className={cx("zu-badge", `t-${props.tone ?? "muted"}`)}>{props.text}</span>
  ),
});

// ---------- data ----------
export const Stat = defineComponent({
  name: "Stat",
  description: 'A labelled value, e.g. Stat("第", "3 章").',
  props: z.object({
    label: z.string(),
    value: z.union([z.string(), z.number()]),
    hint: z.string().optional(),
  }),
  component: ({ props }) => (
    <div className="zu-stat">
      <span className="zu-stat-l">{props.label}</span>
      <span className="zu-stat-v">{String(props.value)}</span>
      {props.hint ? <span className="zu-stat-h">{props.hint}</span> : null}
    </div>
  ),
});
export const Meter = defineComponent({
  name: "Meter",
  description: "A labelled bar for a stat (hp, 线索, 声望...). max defaults to 100.",
  props: z.object({
    label: z.string(),
    value: z.number(),
    max: z.number().optional(),
    tone: tone.optional(),
  }),
  component: function MeterView({ props }) {
    const max = props.max && props.max > 0 ? props.max : 100;
    const pct = Math.max(0, Math.min(100, (Number(props.value) / max) * 100));
    return (
      <div className={cx("zu-meter", `t-${props.tone ?? "gold"}`)}>
        <div className="zu-meter-top">
          <span>{props.label}</span>
          <span className="zu-num">
            {Math.round(Number(props.value))}
            <small>/{max}</small>
          </span>
        </div>
        <div
          className="zu-meter-track"
          role="meter"
          aria-valuenow={props.value}
          aria-valuemax={max}
          aria-label={props.label}
        >
          <div className="zu-meter-fill" style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  },
});
export const Button = defineComponent({
  name: "Button",
  description:
    "Action button. Without action it advances the story with its label (@Act). Use @Act/@Ask/@Inject/@ToAssistant.",
  props: z.object({
    label: z.string(),
    action: action().optional(),
    variant: z.enum(["solid", "ghost"]).optional(),
  }),
  component: function ButtonView({ props }) {
    const trigger = useTriggerAction();
    const streaming = useIsStreaming();
    const label = String(props.label ?? "");
    return (
      <button
        type="button"
        className={cx("zu-btn", props.variant === "ghost" && "ghost")}
        disabled={streaming}
        onClick={() => void trigger(label, undefined, (props.action ?? actPlan(label)) as Plan)}
      >
        {label}
      </button>
    );
  },
});

// ---------- narrative widgets ----------
const nodeSchema = z.object({
  id: z.string(),
  label: z.string(),
  role: z.string().optional(),
  mood: z.string().optional(),
  emoji: z.string().optional(),
  is_player: z.boolean().optional(),
});
const edgeSchema = z.object({
  source: z.string(),
  target: z.string(),
  type: z.string().optional(),
  affinity: z.number().optional(),
});

function affinityColor(a = 0) {
  if (a >= 30) return "var(--jade)";
  if (a <= -30) return "var(--rose)";
  return "var(--muted)";
}

export const RelationGraph = defineComponent({
  name: "RelationGraph",
  description:
    "Interactive character relationship graph. nodes [{id,label,role?,mood?,emoji?,is_player?}], edges [{source,target,type?,affinity -100..100}]. Tap a node for details.",
  props: z.object({ nodes: z.array(nodeSchema), edges: z.array(edgeSchema).optional() }),
  component: function RelationGraphView({ props }) {
    const { act, streaming } = useAct();
    const nodes = useMemo(
      () => (Array.isArray(props.nodes) ? props.nodes.filter((n) => n && n.id) : []),
      [props.nodes],
    );
    const edges = useMemo(
      () => (Array.isArray(props.edges) ? props.edges.filter((e) => e && e.source && e.target) : []),
      [props.edges],
    );
    const [sel, setSel] = useState<string | null>(null);
    const selected = nodes.find((n) => n.id === sel);
    const related = edges.filter((e) => sel && (e.source === sel || e.target === sel));
    if (!nodes.length) return <p className="zu-text c-muted s-sm">尚无人物关系</p>;
    return (
      <div className="zu-graph" role="group" aria-label="人物关系图">
        <RelationCanvas nodes={nodes} edges={edges} selected={sel} onSelect={setSel} />
        <ul className="sr-only">
          {nodes.map((n) => (
            <li key={n.id}>
              {n.label}
              {n.role ? `（${n.role}）` : ""}
            </li>
          ))}
        </ul>
        {selected ? (
          <div className="zu-pop" role="dialog" aria-label={selected.label}>
            <div className="zu-pop-h">
              <strong>{selected.label}</strong>
              {selected.role ? <span className="zu-badge t-muted">{selected.role}</span> : null}
              {selected.mood ? <span className="zu-badge t-azure">{selected.mood}</span> : null}
              <button type="button" className="zu-pop-x" aria-label="关闭" onClick={() => setSel(null)}>
                ×
              </button>
            </div>
            <ul className="zu-pop-list">
              {related.map((e, i) => {
                const other = nodes.find((n) => n.id === (e.source === sel ? e.target : e.source));
                return (
                  <li key={i}>
                    <span>
                      {e.source === sel ? "→ " : "← "}
                      {other?.label ?? "?"}
                    </span>
                    <span className="c-muted">{e.type ?? "关系"}</span>
                    <span className="zu-num" style={{ color: affinityColor(e.affinity) }}>
                      {(e.affinity ?? 0) > 0 ? "+" : ""}
                      {e.affinity ?? 0}
                    </span>
                  </li>
                );
              })}
            </ul>
            {!selected.is_player ? (
              <button
                type="button"
                className="zu-btn sm"
                disabled={streaming}
                onClick={() => act(`去找${selected.label}谈谈`)}
              >
                去找{selected.label}谈谈
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  },
});

const locSchema = z.object({
  id: z.string(),
  name: z.string(),
  x: z.number(),
  y: z.number(),
  description: z.string().optional(),
  characters: z.array(z.string()).optional(),
});

export const WorldMap = defineComponent({
  name: "WorldMap",
  description:
    "Interactive world map. locations [{id,name,x 0..100,y 0..100,description?,characters?}], edges [{source,target}], current = player location id. Tap a place to travel.",
  props: z.object({
    locations: z.array(locSchema),
    edges: z.array(z.object({ source: z.string(), target: z.string() })).optional(),
    current: z.string().optional(),
  }),
  component: function WorldMapView({ props }) {
    const { act, streaming } = useAct();
    const locs = useMemo(
      () => (Array.isArray(props.locations) ? props.locations.filter((l) => l && l.id) : []),
      [props.locations],
    );
    const roads = useMemo(
      () => (Array.isArray(props.edges) ? props.edges.filter((e) => e && e.source && e.target) : []),
      [props.edges],
    );
    const [sel, setSel] = useState<string | null>(null);
    const s = sel ? locs.find((l) => l.id === sel) : null;
    if (!locs.length) return <p className="zu-text c-muted s-sm">地图尚未展开</p>;
    return (
      <div className="zu-map" role="group" aria-label="世界地图">
        <MapCanvas locations={locs} edges={roads} current={props.current} selected={sel} onSelect={setSel} />
        <ul className="sr-only">
          {locs.map((l) => (
            <li key={l.id}>
              {l.name}
              {l.id === props.current ? "（当前位置）" : ""}
            </li>
          ))}
        </ul>
        {s ? (
          <div className="zu-pop zu-pop-map">
            <div className="zu-pop-h">
              <strong>{s.name}</strong>
              {s.id === props.current ? <span className="zu-badge t-gold">你在这里</span> : null}
              <button type="button" className="zu-pop-x" aria-label="关闭" onClick={() => setSel(null)}>
                ×
              </button>
            </div>
            {s.description ? <p className="zu-text s-xs c-muted">{s.description}</p> : null}
            {s.characters?.length ? <p className="zu-text s-xs">在场：{s.characters.join("、")}</p> : null}
            {s.id !== props.current ? (
              <button
                type="button"
                className="zu-btn sm"
                disabled={streaming}
                onClick={() => act(`前往${s.name}`)}
              >
                前往{s.name}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  },
});

const itemSchema = z.object({
  id: z.string().optional(),
  name: z.string(),
  description: z.string().optional(),
  quantity: z.number().optional(),
  icon: z.string().optional(),
});
export const Inventory = defineComponent({
  name: "Inventory",
  description:
    "The player's bag. items [{name, description?, quantity?, icon?}]. Tap an item to inspect or use it.",
  props: z.object({ items: z.array(itemSchema) }),
  component: function InventoryView({ props }) {
    const { act, streaming } = useAct();
    const items = Array.isArray(props.items) ? props.items.filter((i) => i && i.name) : [];
    const [sel, setSel] = useState<number | null>(null);
    if (!items.length) return <p className="zu-text c-muted s-sm">行囊空空</p>;
    const s = sel != null ? items[sel] : null;
    return (
      <div className="zu-inv">
        <div className="zu-inv-grid">
          {items.map((it, i) => (
            <button
              key={it.id ?? i}
              type="button"
              className={cx("zu-slot", sel === i && "on")}
              onClick={() => setSel(sel === i ? null : i)}
              title={it.description}
            >
              <span className="zu-slot-i" aria-hidden>
                {it.icon || it.name.slice(0, 1)}
              </span>
              <span className="zu-slot-n">{it.name}</span>
              {(it.quantity ?? 1) > 1 ? <span className="zu-slot-q">×{it.quantity}</span> : null}
            </button>
          ))}
        </div>
        {s ? (
          <div className="zu-inv-detail">
            <strong>{s.name}</strong>
            {s.description ? <p className="zu-text s-xs c-muted">{s.description}</p> : null}
            <div className="zu-row" style={{ gap: 8 }}>
              <button
                type="button"
                className="zu-btn sm"
                disabled={streaming}
                onClick={() => act(`使用${s.name}`)}
              >
                使用
              </button>
              <button
                type="button"
                className="zu-btn sm ghost"
                disabled={streaming}
                onClick={() => act(`仔细查看${s.name}`)}
              >
                查看
              </button>
            </div>
          </div>
        ) : null}
      </div>
    );
  },
});

export const EventLine = defineComponent({
  name: "EventLine",
  description:
    'One timeline entry: summary, time label, kind "offscreen"|"world"|"player"|"injected"|"npc_action".',
  props: z.object({
    summary: z.string(),
    time: z.string().optional(),
    kind: z.string().optional(),
    impact: z.string().optional(),
  }),
  component: ({ props }) => (
    <div className={cx("zu-evt", `k-${props.kind ?? "world"}`)}>
      <span className="zu-evt-dot" aria-hidden />
      <div>
        <p className="zu-text s-sm">
          <Markdown inline text={props.summary} />
        </p>
        <p className="zu-text s-xs c-muted">
          {[props.time, kindLabel(props.kind), props.impact].filter(Boolean).join(" · ")}
        </p>
      </div>
    </div>
  ),
});
export function kindLabel(k?: string) {
  return (
    { offscreen: "场外", world: "世界", player: "你", injected: "天意", npc_action: "人物" } as Record<
      string,
      string
    >
  )[k ?? ""];
}

export const KnowledgeCard = defineComponent({
  name: "KnowledgeCard",
  description: "Education-mode flip card: title on the front, content and source on the back.",
  props: z.object({ title: z.string(), content: z.string(), source: z.string().optional() }),
  component: ({ props }) => <FlipCard {...props} />,
});

function FlipCard({ title, content, source }: { title: string; content: string; source?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <button
      type="button"
      className={cx("zu-kc", open && "open")}
      onClick={() => setOpen(!open)}
      aria-expanded={open}
      data-testid="knowledge-card"
    >
      <span className="zu-kc-inner">
        <span className="zu-kc-front">
          <span className="zu-kc-tag">知识点</span>
          <strong>{title}</strong>
          <span className="zu-kc-hint">轻触翻面</span>
        </span>
        <span className="zu-kc-back">
          <span className="zu-text s-sm">
            <Markdown inline text={content} />
          </span>
          {source ? <span className="zu-text s-xs c-muted">出处：{source}</span> : null}
        </span>
      </span>
    </button>
  );
}

export const Choices = defineComponent({
  name: "Choices",
  description: "A list of story choices; each runs @Act with its text. options [{id?, text, hint?}].",
  props: z.object({
    options: z.array(z.object({ id: z.string().optional(), text: z.string(), hint: z.string().optional() })),
  }),
  component: function ChoicesView({ props }) {
    const { act, streaming } = useAct();
    return (
      <div className="zu-col" style={{ gap: 8 }}>
        {(props.options ?? []).filter(Boolean).map((o, i) => (
          <button
            key={o.id ?? i}
            type="button"
            className="zu-choice"
            disabled={streaming}
            onClick={() => act(o.text)}
          >
            <span className="zu-num">{String(i + 1).padStart(2, "0")}</span>
            <span>{o.text}</span>
          </button>
        ))}
      </div>
    );
  },
});

export function UIFallbackText({ children: c }: { children: ReactNode }) {
  return <p className="zu-text c-muted s-sm">{c}</p>;
}

export const library = createLibrary({
  root: "Col",
  components: [
    Col,
    Row,
    Grid,
    Panel,
    Divider,
    Title,
    Text,
    Badge,
    Stat,
    Meter,
    Button,
    RelationGraph,
    WorldMap,
    Inventory,
    EventLine,
    KnowledgeCard,
    Choices,
  ],
  actions: [Act, Ask, Inject],
  componentGroups: [
    { name: "Layout", components: ["Col", "Row", "Grid", "Panel", "Divider"] },
    { name: "Text", components: ["Title", "Text", "Badge"] },
    { name: "Data", components: ["Stat", "Meter", "Button"] },
    {
      name: "Narrative",
      components: ["RelationGraph", "WorldMap", "Inventory", "EventLine", "KnowledgeCard", "Choices"],
      notes: [
        "- Panels must stay consistent with the given world data: use real names, ids and numbers only.",
        '- tone is one of "ink","muted","gold","rose","jade","azure","danger".',
      ],
    },
  ],
});

export type { Tone };
