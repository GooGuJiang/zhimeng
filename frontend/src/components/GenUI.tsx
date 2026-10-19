"use client";
/**
 * F6 generative UI host. Every panel is an OpenUI Lang program rendered by @openuidev/react-lang:
 *  1. backend-authored `openui` program (LLM UI agent) if it parses against our library,
 *  2. otherwise the deterministic compiler (UIComponent JSON → OpenUI Lang),
 *  3. if rendering still throws, a plain readable fallback so the panel never disappears.
 * Actions from inside panels (@Act / @Ask / @Inject / @ToAssistant) are routed to the page.
 */
import { Component, useMemo, type ReactNode } from "react";
import { createParser, Renderer, type ActionEvent } from "@openuidev/react-lang";
import { library } from "@/openui/library";
import { compileComponent, programFor } from "@/openui/compile";
import type { UIComponent } from "@/lib/types";

export interface GenUIHandlers {
  act?: (text: string) => void;
  ask?: (question: string) => void;
  inject?: (content: string) => void;
}

let parser: ReturnType<typeof createParser> | null = null;
function getParser() {
  if (!parser) parser = createParser(library.toJSONSchema(), library.root);
  return parser;
}

/** Validate an authored program; returns null when it has hard errors. */
function validProgram(program: string): string | null {
  try {
    const r = getParser().parse(program);
    const errs = (r.meta?.errors ?? []).filter((e: { severity?: string }) => e.severity !== "warning");
    return r.root && !errs.length ? program : null;
  } catch {
    return null;
  }
}

export function routeAction(e: ActionEvent, h: GenUIHandlers) {
  const p = (e.params ?? {}) as Record<string, unknown>;
  const text = (k: string) => String(p[k] ?? e.humanFriendlyMessage ?? "").trim();
  switch (e.type) {
    case "Ask":
      return h.ask?.(text("question"));
    case "Inject":
      return h.inject?.(text("content"));
    case "Act":
      return h.act?.(text("text"));
    case "continue_conversation":
      return h.act?.(String(p.message ?? e.humanFriendlyMessage ?? "").trim());
    case "open_url":
      if (typeof p.url === "string" && /^https?:/.test(p.url)) window.open(p.url, "_blank", "noopener");
      return;
    default:
      if (e.humanFriendlyMessage) h.act?.(e.humanFriendlyMessage);
  }
}

class Boundary extends Component<
  { fallback: ReactNode; children: ReactNode; resetKey: string },
  { err: boolean; key: string }
> {
  state = { err: false, key: this.props.resetKey };
  static getDerivedStateFromError() {
    return { err: true };
  }
  static getDerivedStateFromProps(p: { resetKey: string }, s: { err: boolean; key: string }) {
    return p.resetKey !== s.key ? { err: false, key: p.resetKey } : null;
  }
  render() {
    return this.state.err ? this.props.fallback : this.props.children;
  }
}

/** Last-resort, non-OpenUI text rendering of a panel's props. */
function PlainFallback({ c }: { c: UIComponent }) {
  const p = c.props as Record<string, unknown>;
  const entries = Object.entries(p).slice(0, 6);
  return (
    <div className="zu-col" style={{ gap: 4 }}>
      {entries.map(([k, v]) => (
        <p key={k} className="zu-text s-xs c-muted">
          {k}：{Array.isArray(v) ? `${v.length} 项` : typeof v === "object" ? "…" : String(v)}
        </p>
      ))}
    </div>
  );
}

/** Render a raw OpenUI program (used for preview map, knowledge lists, etc.). */
export function OpenUIBlock({
  program,
  handlers = {},
  streaming,
  fallback,
}: {
  program: string;
  handlers?: GenUIHandlers;
  streaming?: boolean;
  fallback?: ReactNode;
}) {
  return (
    <Boundary resetKey={program} fallback={fallback ?? <p className="zu-text c-muted s-sm">界面暂不可用</p>}>
      <div className="zu-root">
        <Renderer
          response={program}
          library={library}
          isStreaming={!!streaming}
          onAction={(e) => routeAction(e as ActionEvent, handlers)}
        />
      </div>
    </Boundary>
  );
}

export function GenUIPanel({
  c,
  handlers,
  streaming,
  source,
}: {
  c: UIComponent;
  handlers: GenUIHandlers;
  streaming?: boolean;
  source: "ai" | "local";
}) {
  const { program, authored } = useMemo(() => {
    const pf = programFor(c);
    if (pf.authored) {
      const ok = validProgram(pf.program);
      if (ok) return { program: ok, authored: true };
    }
    return { program: compileComponent(c), authored: false };
  }, [c]);
  return (
    <section
      className={`genui-panel card flat size-${c.layout?.size ?? "md"}`}
      data-testid={`ui-${c.type}`}
      data-ui-id={c.id}
      aria-label={c.title}
    >
      <div className="card-h">
        <i className="knot" aria-hidden />
        <h3 className="h2" style={{ fontSize: 16 }}>
          {c.title}
        </h3>
        <span
          className="genui-src"
          title={authored ? "由 UI 智能体编写的 OpenUI 程序" : "依剧情数据编译的 OpenUI 程序"}
        >
          {source === "local" ? "本地生成" : authored ? "AI 编排" : "AI 数据"}
        </span>
      </div>
      <OpenUIBlock
        program={program}
        handlers={handlers}
        streaming={streaming}
        fallback={<PlainFallback c={c} />}
      />
    </section>
  );
}

/** The generative area: panels ordered by the backend's priority hint (plot-driven layout). */
export function GenUI({
  components,
  handlers,
  streaming,
  source,
  exclude = [],
}: {
  components: UIComponent[];
  handlers: GenUIHandlers;
  streaming?: boolean;
  source: "ai" | "local";
  exclude?: string[];
}) {
  const sorted = [...components]
    .filter((c) => !exclude.includes(c.type))
    .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
  return (
    <div className="genui stack" data-testid="genui" data-source={source}>
      {sorted.map((c) => (
        <GenUIPanel
          key={`${c.id}-${c.type}`}
          c={c}
          handlers={handlers}
          streaming={streaming}
          source={source}
        />
      ))}
    </div>
  );
}
