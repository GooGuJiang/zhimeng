"use client";
/** 设置与安全 (F9): minor mode, rating, motion / font prefs, safety policy, reports, service status. */
import { useEffect, useState } from "react";
import { Flag, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { Rating, World } from "@/lib/types";
import { usePrefs } from "@/hooks/usePrefs";
import { useCurrentWorld } from "@/hooks/useCurrentWorld";
import { ReportDialog } from "@/components/ReportDialog";
import { useToast } from "@/components/Toast";
import { AI_LABEL } from "@/components/AiLabel";

const RATINGS: { v: Rating; l: string; d: string }[] = [
  { v: "all", l: "全年龄", d: "无暴力细节、无恐怖与成人内容" },
  { v: "teen", l: "青少年", d: "允许轻度冲突与悬疑，不含血腥与色情" },
  { v: "mature", l: "成人", d: "允许更沉重的题材，仍拒绝违法与有害内容" },
];

type Health = Awaited<ReturnType<typeof api.health>>;
type Policy = Awaited<ReturnType<typeof api.policy>>;

export function SettingsView() {
  const toast = useToast();
  const [prefs, setPrefs] = usePrefs();
  const [worldId] = useCurrentWorld();
  const [world, setWorld] = useState<World | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthErr, setHealthErr] = useState(false);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [reports, setReports] = useState<
    { id: string; reason?: string; status?: string; created_at?: string }[]
  >([]);
  const [reporting, setReporting] = useState(false);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setHealthErr(true));
    api
      .policy()
      .then(setPolicy)
      .catch(() => {});
    fetch("/api/reports")
      .then((r) => (r.ok ? r.json() : []))
      .then((r) => setReports(Array.isArray(r) ? r : []))
      .catch(() => {});
  }, [reporting]);
  useEffect(() => {
    if (worldId)
      api
        .getWorld(worldId)
        .then(setWorld)
        .catch(() => setWorld(null));
  }, [worldId]);

  const patch = async (body: { minor_mode?: boolean; rating?: Rating }) => {
    if (!world) return;
    try {
      setWorld(await api.patchSettings(world.id, body));
      toast("当前世界的安全设置已更新");
    } catch (e) {
      toast(`更新失败：${(e as Error).message}`);
    }
  };

  return (
    <div className="stack settings">
      <div>
        <div className="eyebrow">设置与安全</div>
        <h1 className="h1">让故事在安全的边界里自由生长</h1>
      </div>
      <div className="grid-2" style={{ alignItems: "start" }}>
        <div className="stack">
          <section className="card">
            <div className="card-h">
              <ShieldCheck size={16} aria-hidden />
              <h2 className="h2">未成年人模式与分级</h2>
            </div>
            <div className="stack">
              <label className="switch">
                <input
                  type="checkbox"
                  data-testid="minor-mode-toggle"
                  checked={prefs.minorMode}
                  onChange={(e) => setPrefs({ minorMode: e.target.checked })}
                />
                新建世界默认开启未成年人模式
              </label>
              {world ? (
                <>
                  <hr className="zu-divider" />
                  <p className="muted" style={{ margin: 0 }}>
                    当前世界《{world.title}》
                  </p>
                  <label className="switch">
                    <input
                      type="checkbox"
                      checked={world.minor_mode}
                      onChange={(e) => void patch({ minor_mode: e.target.checked })}
                    />
                    此世界启用未成年人模式
                  </label>
                  <div className="rating-list" role="radiogroup" aria-label="内容分级">
                    {RATINGS.map((r) => (
                      <button
                        key={r.v}
                        type="button"
                        role="radio"
                        aria-checked={world.rating === r.v}
                        className={`rating${world.rating === r.v ? " on" : ""}`}
                        disabled={world.minor_mode && r.v !== "all"}
                        onClick={() => void patch({ rating: r.v })}
                      >
                        <strong>{r.l}</strong>
                        <span>{r.d}</span>
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <p className="faint" style={{ margin: 0 }}>
                  进入一个世界后，可在这里调整它的分级。
                </p>
              )}
            </div>
          </section>
          <section className="card">
            <div className="card-h">
              <i className="knot" aria-hidden />
              <h2 className="h2">阅读与动效</h2>
            </div>
            <div className="stack">
              <div className="field">
                <span>动画效果</span>
                <div className="chips">
                  {(
                    [
                      ["system", "跟随系统"],
                      ["on", "开启"],
                      ["off", "减少动效（低性能设备）"],
                    ] as const
                  ).map(([v, l]) => (
                    <button
                      key={v}
                      type="button"
                      className={`chip${prefs.reducedMotion === v ? " on" : ""}`}
                      onClick={() => setPrefs({ reducedMotion: v })}
                    >
                      {l}
                    </button>
                  ))}
                </div>
              </div>
              <label className="field">
                <span>叙事字号 {Math.round(prefs.fontScale * 100)}%</span>
                <input
                  type="range"
                  min={0.85}
                  max={1.3}
                  step={0.05}
                  value={prefs.fontScale}
                  onChange={(e) => setPrefs({ fontScale: Number(e.target.value) })}
                />
              </label>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={prefs.autoVoice}
                  onChange={(e) => setPrefs({ autoVoice: e.target.checked })}
                />
                关键场景自动播放配音
              </label>
            </div>
          </section>
        </div>
        <div className="stack">
          <section className="card">
            <div className="card-h">
              <i className="knot" aria-hidden />
              <h2 className="h2">内容安全承诺</h2>
            </div>
            <ul className="points">
              <li>输入与生成内容双向过滤：关键词 + 模型审核。</li>
              <li>所有 AI 生成内容均标注「{policy?.ai_label || AI_LABEL}」。</li>
              <li>危机类表达不会进入剧情，而是优先给出求助热线。</li>
              <li>API 密钥只保存在服务端，浏览器不接触任何密钥。</li>
            </ul>
            {policy?.crisis_message ? <div className="notice crisis">{policy.crisis_message}</div> : null}
            <div className="row" style={{ marginTop: 14 }}>
              <button
                type="button"
                className="btn ghost"
                data-testid="report-btn"
                onClick={() => setReporting(true)}
              >
                <Flag size={14} aria-hidden /> 举报 / 反馈
              </button>
              <span className="faint" style={{ fontSize: 12 }}>
                已提交 {reports.length} 条
              </span>
            </div>
          </section>
          <section className="card flat">
            <div className="card-h">
              <i className="knot" aria-hidden />
              <h2 className="h2">服务状态</h2>
            </div>
            {health ? (
              <div className="stack" style={{ gap: 6, fontSize: 14 }}>
                <div>
                  模式：
                  {health.llm && !health.fallback ? (
                    <span className="tag jade">大模型在线</span>
                  ) : (
                    <span className="tag">本地兜底模板（未配置模型密钥）</span>
                  )}
                </div>
                {Object.entries(health.models ?? {}).map(([k, v]) => (
                  <div key={k} className="faint">
                    {k}：{v}
                  </div>
                ))}
                <div className="faint">版本 {health.version}</div>
              </div>
            ) : healthErr ? (
              <div className="notice warn">后端服务不可达，请确认 http://localhost:8000 已启动。</div>
            ) : (
              <div className="skel" style={{ height: 60 }} />
            )}
          </section>
        </div>
      </div>
      {reporting ? (
        <ReportDialog
          worldId={world?.id}
          content={world ? `世界《${world.title}》` : "用户反馈"}
          onClose={() => setReporting(false)}
        />
      ) : null}
    </div>
  );
}
