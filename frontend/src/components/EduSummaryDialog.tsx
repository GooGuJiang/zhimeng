"use client";
/** F10 学习小结: key points, timeline, interactive quiz, reflection. */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { EducationSummary } from "@/lib/types";
import { Dialog } from "./Dialog";
import { AiLabel } from "./AiLabel";
import { KnowledgeCards } from "./WorldBits";

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
            <li key={i}>{k}</li>
          ))}
        </ul>
      </section>
      {s.timeline?.length ? (
        <section>
          <div className="eyebrow">你的探索时间线</div>
          {s.timeline.map((t, i) => (
            <div key={i} className="timeline-row">
              <span className="num faint">第 {t.turn} 回合</span>
              <span>{t.summary}</span>
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
                  {picked[qi] === q.answer_index ? "✓ 答对了。" : "✗ 再想想。"} {q.explanation}
                </p>
              ) : null}
            </div>
          ))}
        </section>
      ) : null}
      {s.reflection ? (
        <section>
          <div className="eyebrow">课后反思</div>
          <p className="serif" style={{ margin: 0 }}>
            {s.reflection}
          </p>
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

export function EduSummaryDialog({ worldId, onClose }: { worldId: string; onClose: () => void }) {
  const [s, setS] = useState<EducationSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api
      .eduSummary(worldId)
      .then(setS)
      .catch((e) => setErr((e as Error).message));
  }, [worldId]);
  return (
    <Dialog title="学习小结" onClose={onClose} wide>
      {s ? (
        <EduSummaryView s={s} />
      ) : err ? (
        <div className="notice warn">{err}</div>
      ) : (
        <div className="skel" style={{ height: 200 }} />
      )}
    </Dialog>
  );
}
