"use client";
/**
 * "织机" thinking visualisation: warp threads + a shuttle weaving while the AI works,
 * with the backend's progress stages lit up as they arrive. Degrades to static under reduced motion (CSS).
 */
import type { Progress } from "@/lib/types";

export const STAGE_LABELS: Record<string, string> = {
  safety: "安全审查",
  outline: "勾勒世界",
  locations: "铺陈地理",
  characters: "唤醒众生",
  conflict: "埋下冲突",
  persist: "落笔存档",
  memory: "检索记忆",
  world: "推演时局",
  npc: "众生行动",
  director: "导演编织",
  narrate: "落笔成文",
  extract: "提炼事实",
  ui: "编织界面",
  asset: "绘图配音",
};

export function Loom({
  stages,
  progress,
  compact,
  testId,
  title,
}: {
  stages: string[];
  progress: Progress | null;
  compact?: boolean;
  testId?: string;
  title?: string;
}) {
  const idx = progress ? stages.indexOf(progress.stage) : -1;
  const pct = Math.max(4, Math.min(100, progress?.pct ?? 4));
  return (
    <div className={`loom${compact ? " compact" : ""}`} data-testid={testId} role="status" aria-live="polite">
      <svg className="loom-svg" viewBox="0 0 100 100" aria-hidden>
        {Array.from({ length: 9 }, (_, i) => (
          <line key={i} className="warp" x1={14 + i * 9} y1={12} x2={14 + i * 9} y2={88} />
        ))}
        <path className="weft" d="M10 34 C 30 24, 50 44, 70 34 S 90 30, 92 34" />
        <path className="weft" d="M10 52 C 30 42, 50 62, 70 52 S 90 48, 92 52" />
        <path className="weft" d="M10 70 C 30 60, 50 80, 70 70 S 90 66, 92 70" />
        <g transform="translate(50 52)">
          <ellipse className="shuttle" rx="7" ry="2.6" />
        </g>
      </svg>
      <div>
        {title ? <div className="eyebrow">{title}</div> : null}
        {!compact ? (
          <div className="loom-stages">
            {stages.map((s, i) => (
              <span key={s} className={`loom-stage${i < idx ? " done" : i === idx ? " now" : ""}`}>
                {STAGE_LABELS[s] ?? s}
              </span>
            ))}
          </div>
        ) : null}
        <div className="loom-msg">
          {progress?.message || "织机启动中"}
          <span className="dots" aria-hidden>
            <i />
            <i />
            <i />
          </span>
        </div>
        <div className="loom-bar">
          <i style={{ width: `${pct}%` }} />
        </div>
      </div>
    </div>
  );
}
