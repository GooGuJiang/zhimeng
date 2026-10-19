"use client";
/** F4 memory Q&A with citations (第几章·第几回合). */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Citation } from "@/lib/types";
import { AiLabel } from "./AiLabel";

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

  const ask = async (question = q) => {
    if (!question.trim() || busy) return;
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.queryMemory(worldId, question.trim(), 5));
    } catch (e) {
      setErr((e as Error).message);
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
        className="row"
        style={{ flexWrap: "nowrap" }}
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
        <button type="submit" className="btn" data-testid="memory-query-btn" disabled={busy || !q.trim()}>
          {busy ? "追忆中…" : "回忆"}
        </button>
      </form>
      {err ? <div className="notice warn">{err}</div> : null}
      {res ? (
        <div className="stack memory-result" data-testid="memory-answer">
          <div className="row">
            <span className="eyebrow">世界的回答</span>
            <AiLabel text={res.ai_label} />
          </div>
          <p className="answer" style={{ margin: 0 }}>
            {res.answer}
          </p>
          {res.citations?.length ? (
            <div className="stack" style={{ gap: 8 }}>
              <span className="faint" style={{ fontSize: 12 }}>
                出处
              </span>
              {res.citations.map((c, i) => (
                <div key={c.fact_id || i} className="citation" data-testid="citation">
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
