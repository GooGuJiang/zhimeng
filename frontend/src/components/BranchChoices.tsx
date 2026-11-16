"use client";
/** Per-turn character branch choices: 2–4 clickable options with a short consequence hint, plus free input. */
import type { Option } from "@/lib/types";
import { withHints } from "@/lib/branches";

export function BranchChoices({
  options,
  disabled,
  takenIds,
  onPick,
}: {
  options: Option[];
  disabled?: boolean;
  takenIds?: Iterable<string>;
  onPick: (option: Option) => void;
}) {
  const taken = new Set(takenIds ?? []);
  const list = withHints(options).slice(0, 4);
  if (!list.length) return null;
  return (
    <div className="options branch-choices" aria-label="角色分支选择" data-testid="branch-choices">
      <div className="branch-choices-h">接下来，你选择？</div>
      {list.map((o, i) => (
        <button
          key={o.id || `opt-${i}`}
          type="button"
          className="option"
          data-testid="option-btn"
          data-option={o.id}
          disabled={disabled}
          onClick={() => onPick(o)}
          style={{ animationDelay: `${i * 60}ms` }}
        >
          <span className="num">{String(i + 1).padStart(2, "0")}</span>
          <span>
            <span className="option-text">
              {o.text}
              {taken.has(o.id) ? <span className="tag" data-testid="option-taken">已走过</span> : null}
            </span>
            {o.hint ? <small data-testid="option-hint">{o.hint}</small> : null}
          </span>
        </button>
      ))}
    </div>
  );
}
