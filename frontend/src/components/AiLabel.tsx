/**
 * F9 AI-content label. The data (`ai_generated` / `ai_label` from the API) is always kept; whether the
 * visible badge is rendered is a build-time switch requested by the user:
 *   NEXT_PUBLIC_ZM_SHOW_AI_LABEL=1  → show 「内容由AI生成」 badges, poster/video label lines, panel source tags
 *   unset / 0 (default)             → render nothing (no empty gaps)
 */
export const AI_LABEL = "内容由AI生成";

const flag = (process.env.NEXT_PUBLIC_ZM_SHOW_AI_LABEL ?? "").toLowerCase();
export const SHOW_AI_LABEL = flag === "1" || flag === "true" || flag === "yes" || flag === "on";

export function AiLabel({ text, testId = "ai-label" }: { text?: string | null; testId?: string }) {
  if (!SHOW_AI_LABEL) return null;
  return (
    <span className="ai-label" data-testid={testId} title="本内容由人工智能生成，仅供娱乐与学习参考">
      {text || AI_LABEL}
    </span>
  );
}
