/** F9: every AI-generated surface carries this marker. */
export const AI_LABEL = "内容由AI生成";

export function AiLabel({ text, testId = "ai-label" }: { text?: string | null; testId?: string }) {
  return (
    <span className="ai-label" data-testid={testId} title="本内容由人工智能生成，仅供娱乐与学习参考">
      {text || AI_LABEL}
    </span>
  );
}
