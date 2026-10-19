import { ShieldAlert, LifeBuoy } from "lucide-react";
import type { SafetyResult } from "@/lib/types";

const CAT: Record<string, string> = {
  violence: "暴力",
  weapons: "危险物品",
  self_harm: "自我伤害",
  sexual: "色情",
  minor: "未成年人保护",
  hate: "仇恨歧视",
  illegal: "违法犯罪",
  politics: "敏感话题",
  drugs: "毒品",
};

/** F9: blocked input / crisis interception message. Crisis content shows the help hotline first. */
export function SafetyNotice({ result, onClose }: { result: SafetyResult; onClose?: () => void }) {
  const crisis = result.crisis;
  const fallback = crisis
    ? "你并不孤单。如果你正处在痛苦中，请立即联系身边信任的人，或拨打全国心理援助热线 400-161-9995、北京心理危机干预中心 010-82951332；紧急情况请拨打 110 / 120。"
    : "该内容未通过安全审核，已被拦截，本回合未计入进度。请换一种方式继续你的故事。";
  return (
    <div
      className={`notice ${crisis ? "crisis" : "warn"} safety-notice`}
      data-testid="safety-notice"
      role="alert"
    >
      <div className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
        {crisis ? <LifeBuoy size={18} aria-hidden /> : <ShieldAlert size={18} aria-hidden />}
        <div style={{ flex: 1 }}>
          <strong>
            {crisis ? "我们注意到你可能需要帮助" : result.blocked ? "内容已被安全拦截" : "内容已按分级过滤"}
          </strong>
          <p style={{ margin: "4px 0 0" }}>{result.message || fallback}</p>
          {result.categories?.length ? (
            <p className="faint" style={{ margin: "4px 0 0", fontSize: 12 }}>
              类别：{result.categories.map((c) => CAT[c] ?? c).join("、")} · 分级：{result.rating}
            </p>
          ) : null}
        </div>
        {onClose ? (
          <button type="button" className="linkish" onClick={onClose}>
            知道了
          </button>
        ) : null}
      </div>
    </div>
  );
}
