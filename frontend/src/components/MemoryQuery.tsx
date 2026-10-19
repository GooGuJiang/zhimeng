"use client";
/** F4 memory Q&A with citations (第几章·第几回合). */
import { Markdown } from "./Markdown";
import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Loader2, Search } from "lucide-react";
import { api, errorText } from "@/lib/api";
import type { Citation } from "@/lib/types";
import { AiLabel } from "./AiLabel";

/**
 * The model cites sources as [1] / [1][2] / [1,2]. Turn each valid index into a `#zm-cite-n` link
 * (rendered by <Markdown> as a small superscript badge); drop indices that have no 出处 card.
 */
export function linkCitations(answer: string, count: number): string {
  return answer.replace(/\[(\d{1,2}(?:\s*[,，、]\s*\d{1,2})*)\](?!\()/g, (_, list: string) =>
    list
      .split(/\s*[,，、]\s*/)
      .map(Number)
      .filter((n) => n >= 1 && n <= count)
      .map((n) => `[${n}](#zm-cite-${n})`)
      .join(""),
  );
}

export function MemoryQuery({
  worldId,
  initialQuestion,
}: {
  worldId: string;
  initialQuestion?: string | null;
}) {
  const [q, setQ] = useState(initialQuestion ?? "");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ answer: string; citations: Citation[]; ai_label?: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [hot, setHot] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const hotTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(hotTimer.current), []);
  const onAnswerClick = (e: MouseEvent) => {
    const a = (e.target as HTMLElement).closest<HTMLElement>("[data-cite]");
    if (!a) return;
    e.preventDefault();
    const n = Number(a.dataset.cite);
    listRef.current
      ?.querySelector(`[data-cite-card="${n}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    setHot(n);
    clearTimeout(hotTimer.current);
    hotTimer.current = setTimeout(() => setHot(null), 1800);
  };

  const ask = async (question = q) => {
    if (!question.trim() || busy) return;
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.queryMemory(worldId, question.trim(), 5));
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  // Parent remounts us (key) for a new @Ask question from the generative UI: run it once.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (initialQuestion) void ask(initialQuestion);
  }, [initialQuestion]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="stack">
      <form
        className="memory-form"
        onSubmit={(e) => {
          e.preventDefault();
          void ask();
        }}
      >
        <input
          className="input"
          data-testid="memory-query-input"
          placeholder="问问世界的记忆，如：第一章那个线人叫什么？"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          maxLength={200}
        />
        <button
          type="submit"
          className="btn memory-btn"
          data-testid="memory-query-btn"
          disabled={busy || !q.trim()}
          aria-busy={busy}
        >
          {busy ? <Loader2 size={15} className="spin" aria-hidden /> : <Search size={15} aria-hidden />}
          <span>{busy ? "追忆中" : "回忆"}</span>
        </button>
      </form>
      {err ? (
        <div className="notice warn row" role="alert" data-testid="memory-error">
          <span style={{ flex: 1 }}>{err}</span>
          <button type="button" className="btn sm ghost" onClick={() => void ask()}>
            重试
          </button>
        </div>
      ) : null}
      {busy ? (
        <p className="faint" data-testid="memory-loading" style={{ margin: 0, fontSize: 13 }}>
          正在检索世界记忆并组织回答…（真实模型可能需要十几秒）
        </p>
      ) : null}
      {res ? (
        <div className="stack memory-result" data-testid="memory-answer">
          <div className="row">
            <span className="eyebrow">世界的回答</span>
            <AiLabel text={res.ai_label} />
          </div>
          <div onClick={onAnswerClick}>
            <Markdown className="answer" text={linkCitations(res.answer, res.citations?.length ?? 0)} />
          </div>
          {res.citations?.length ? (
            <div className="stack" style={{ gap: 8 }} ref={listRef}>
              <span className="faint" style={{ fontSize: 12 }}>
                出处
              </span>
              {res.citations.map((c, i) => (
                <div
                  key={c.fact_id || i}
                  className={`citation${hot === i + 1 ? " hot" : ""}`}
                  data-testid="citation"
                  data-cite-card={i + 1}
                >
                  <span className="cite-n" aria-label={`出处 ${i + 1}`}>
                    {i + 1}
                  </span>
                  <span className="src">{c.source || `第${c.chapter}章·第${c.turn}回合`}</span>
                  <span>{c.content}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="faint">（未找到明确出处）</p>
          )}
        </div>
      ) : null}
    </div>
  );
}
