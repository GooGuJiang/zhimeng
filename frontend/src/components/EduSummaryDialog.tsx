"use client";
/** F10 学习小结: key points, timeline, interactive quiz, reflection. */
import { Markdown } from "./Markdown";
import { useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";
import { Loom } from "./Loom";
import type { EducationSummary } from "@/lib/types";
import { Dialog } from "./Dialog";
import { AiLabel } from "./AiLabel";
import { KnowledgeCards } from "./WorldBits";
import { SHOW_AI_LABEL } from "./AiLabel";

export function EduSummaryView({ s }: { s: EducationSummary }) {
  const [picked, setPicked] = useState<Record<number, number>>({});
  return (
    <div className="stack edu-summary" data-testid="edu-summary">
      <div className="row">
        <h3 className="h2" style={{ flex: 1 }}>
          {s.title}
        </h3>
        <AiLabel text={s.ai_label} />
      </div>
      <section>
        <div className="eyebrow">知识要点</div>
        <ul className="points">
          {s.key_points.map((k, i) => (
            <li key={i}>
              <Markdown inline text={k} />
            </li>
          ))}
        </ul>
      </section>
      {s.timeline?.length ? (
        <section>
          <div className="eyebrow">你的探索时间线</div>
          {s.timeline.map((t, i) => (
            <div key={i} className="timeline-row">
              <span className="num faint">第 {t.turn} 回合</span>
              <Markdown inline text={t.summary} />
            </div>
          ))}
        </section>
      ) : null}
      {s.quiz?.length ? (
        <section className="stack">
          <div className="eyebrow">小测验</div>
          {s.quiz.map((q, qi) => (
            <div key={qi} className="quiz card flat">
              <p style={{ margin: "0 0 8px" }}>
                {qi + 1}. {q.question}
              </p>
              <div className="chips">
                {q.options.map((o, oi) => {
                  const chosen = picked[qi] === oi;
                  const reveal = picked[qi] !== undefined;
                  const cls = reveal && oi === q.answer_index ? " right" : chosen ? " wrong" : "";
                  return (
                    <button
                      key={oi}
                      type="button"
                      className={`chip${cls}`}
                      onClick={() => setPicked({ ...picked, [qi]: oi })}
                      disabled={reveal}
                    >
                      {o}
                    </button>
                  );
                })}
              </div>
              {picked[qi] !== undefined ? (
                <p className="faint" style={{ margin: "8px 0 0", fontSize: 13 }}>
                  {picked[qi] === q.answer_index ? "✓ 答对了。" : "✗ 再想想。"}{" "}
                  <Markdown inline text={q.explanation} />
                </p>
              ) : null}
            </div>
          ))}
        </section>
      ) : null}
      {s.reflection ? (
        <section>
          <div className="eyebrow">课后反思</div>
          <Markdown className="serif" text={s.reflection} />
        </section>
      ) : null}
      {s.cards?.length ? (
        <section>
          <div className="eyebrow">已解锁知识卡</div>
          <KnowledgeCards cards={s.cards} />
        </section>
      ) : null}
    </div>
  );
}

const MAX_POLLS = 6; // ≈ 3 + 4.5 + 6.8 + 10 + 12 + 12 s ≈ 48 s

const SUMMARY_STAGES = ["recall", "points", "quiz", "reflect"];
const SUMMARY_STEPS: Record<string, string> = {
  recall: "回顾你走过的旅程",
  points: "提炼知识要点",
  quiz: "出几道小测验",
  reflect: "写下课后反思",
};

/** Loading/error states for the (slow, LLM-backed) summary — never shows raw server errors. */
export function EduSummaryDialog({ worldId, onClose }: { worldId: string; onClose: () => void }) {
  const [s, setS] = useState<EducationSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const loading = !s && !err;

  // v1.2: the endpoint answers within ~8 s; if the LLM version isn't ready it returns the local summary
  // with status:"pending" — show that right away and re-request with backoff (capped) for "complete".
  const [polls, setPolls] = useState<"idle" | "polling" | "gave-up">("idle");
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let n = 0;
    const load = (first: boolean) =>
      api
        .eduSummary(worldId)
        .then((r) => {
          if (!live) return;
          setS(r);
          if (r.status !== "pending") return setPolls("idle");
          if (++n > MAX_POLLS) return setPolls("gave-up");
          setPolls("polling");
          timer = setTimeout(() => void load(false), Math.min(12_000, 3000 * 1.5 ** (n - 1)));
        })
        .catch((e) => {
          if (!live) return;
          if (first) setErr(errorText(e));
          else setPolls("gave-up"); // keep the local version on screen
        });
    void load(true);
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [worldId, attempt]);

  useEffect(() => {
    if (!loading) return;
    const t0 = Date.now();
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(t);
  }, [loading, attempt]);

  const retry = () => {
    setErr(null);
    setPolls("idle");
    setElapsed(0);
    setAttempt((a) => a + 1);
  };
  const stage = SUMMARY_STAGES[Math.min(SUMMARY_STAGES.length - 1, Math.floor(elapsed / 6))];

  return (
    <Dialog title="学习小结" onClose={onClose} wide>
      {s ? (
        <>
          {s.status === "pending" ? (
            <div
              className="notice row"
              data-testid="edu-summary-pending"
              aria-live="polite"
              style={{ marginBottom: 12, fontSize: 13 }}
            >
              {polls === "gave-up" ? (
                <>
                  <span style={{ flex: 1 }}>
                    {SHOW_AI_LABEL
                      ? "当前为本地整理版，AI 精修版暂未就绪。"
                      : "当前为本地整理版，精修版暂未就绪。"}
                  </span>
                  <button type="button" className="btn sm ghost" onClick={retry}>
                    再试一次
                  </button>
                </>
              ) : (
                <>
                  <span className="dots" aria-hidden>
                    <i />
                    <i />
                    <i />
                  </span>
                  <span>
                    {SHOW_AI_LABEL
                      ? "先为你呈现本地整理版，AI 精修版生成中，完成后自动替换…"
                      : "先为你呈现本地整理版，精修版生成中，完成后自动替换…"}
                  </span>
                </>
              )}
            </div>
          ) : null}
          <EduSummaryView key={s.status ?? "x"} s={s} />
        </>
      ) : err ? (
        <div className="notice warn stack" role="alert" data-testid="edu-summary-error">
          <strong>学习小结暂时没能生成</strong>
          <span>{err}</span>
          <div className="row">
            <button type="button" className="btn sm" data-testid="edu-summary-retry" onClick={retry}>
              重试
            </button>
            <button type="button" className="btn sm ghost" onClick={onClose}>
              稍后再看
            </button>
          </div>
        </div>
      ) : (
        <div className="stack" data-testid="edu-summary-loading" aria-busy="true">
          <Loom
            stages={SUMMARY_STAGES}
            progress={{ stage, message: SUMMARY_STEPS[stage], pct: Math.min(95, 8 + elapsed * 3) }}
            title="正在整理学习小结"
          />
          <p className="faint" style={{ margin: 0, fontSize: 13 }}>
            {elapsed < 8
              ? SHOW_AI_LABEL
                ? "AI 正在回顾你的探索并出题…"
                : "正在回顾你的探索并出题…"
              : `已等待 ${elapsed} 秒，真实模型生成小结通常需要 10–40 秒，请稍候。`}
          </p>
        </div>
      )}
    </Dialog>
  );
}
