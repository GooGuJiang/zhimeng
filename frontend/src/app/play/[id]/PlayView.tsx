"use client";
/** 游玩页 (F2-F9): streamed narration + options + free input, generative UI side panels, off-screen events. */
import Link from "next/link";
import { Fragment, useEffect, useRef, useState } from "react";
import {
  Brain,
  Download,
  Eye,
  Flag,
  GraduationCap,
  Image as ImageIcon,
  RotateCcw,
  Send,
  Share2,
  Volume2,
} from "lucide-react";
import { api, errorText } from "@/lib/api";
import type { Asset, Turn } from "@/lib/types";
import { usePlay, TURN_STAGES } from "@/hooks/usePlay";
import { usePrefs } from "@/hooks/usePrefs";
import { setCurrentWorld } from "@/hooks/useCurrentWorld";
import { downloadBlob } from "@/lib/video";
import { AiLabel } from "@/components/AiLabel";
import { Loom } from "@/components/Loom";
import { GenUI, type GenUIHandlers } from "@/components/GenUI";
import { OffscreenPanel } from "@/components/OffscreenPanel";
import { MemoryQuery } from "@/components/MemoryQuery";
import { ReportDialog } from "@/components/ReportDialog";
import { PosterDialog } from "@/components/PosterDialog";
import { EduSummaryDialog } from "@/components/EduSummaryDialog";
import { SafetyNotice } from "@/components/SafetyNotice";
import { AudioBar, Illustration } from "@/components/MediaBits";
import { mergeAssets } from "@/lib/assets";
import { useToast } from "@/components/Toast";

type ReportTarget = { turnId?: string; content: string };

export function PlayView({ id }: { id: string }) {
  const p = usePlay(id);
  const toast = useToast();
  const [prefs] = usePrefs();
  const [mediaBusy, setMediaBusy] = useState<Record<string, boolean>>({});
  const [input, setInput] = useState("");
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [memoryQ, setMemoryQ] = useState<string | null>(null);
  const [report, setReport] = useState<ReportTarget | null>(null);
  const [posterOpen, setPosterOpen] = useState(false);
  const [eduOpen, setEduOpen] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => setCurrentWorld(id), [id]);
  // keep the newest text in view while it streams
  const liveLen = p.live?.text.length ?? 0;
  useEffect(() => {
    if (p.live) endRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [liveLen, p.live]);

  const { world } = p;
  if (!world)
    return p.loadError ? (
      <div className="empty">
        <h1 className="h1">世界无法载入</h1>
        <p>{p.loadError}</p>
        <Link href="/" className="btn">
          回到开局
        </Link>
      </div>
    ) : (
      <div className="play">
        <div className="card story stack">
          <div className="skel" style={{ height: 28, width: "50%" }} />
          <div className="skel" style={{ height: 120 }} />
          <div className="skel" style={{ height: 80 }} />
        </div>
      </div>
    );

  const handlers: GenUIHandlers = {
    act: (t) => p.send(t),
    ask: (q) => {
      setMemoryOpen(true);
      setMemoryQ(q);
    },
    inject: (content) => {
      api
        .inject(id, { content })
        .then(() => {
          toast(`天意已降：${content}`);
          void p.refreshSide();
        })
        .catch((e) => toast(`干预失败：${errorText(e)}`));
    },
  };

  const submit = () => {
    if (p.send(input)) setInput("");
  };

  const turnIds = new Set(p.turns.map((t) => t.id));
  const assetsFor = (turnId: string | null, isLatest: boolean): Asset[] =>
    p.assets.filter((a) => a.turn_id === turnId || (isLatest && a.turn_id && !turnIds.has(a.turn_id)));
  // a manual illustrate/tts/regenerate result replaces that slot (same id → version-aware merge;
  // a pending placeholder is then long-polled by usePlay until it upgrades).
  const replaceAsset = (a: Asset) =>
    p.setAssets((old) =>
      mergeAssets(
        old.filter((x) => x.id === a.id || !(x.type === a.type && x.turn_id === a.turn_id)),
        [a],
      ),
    );
  const withBusy = async (key: string, fn: () => Promise<void>) => {
    setMediaBusy((m) => ({ ...m, [key]: true }));
    try {
      await fn();
    } finally {
      setMediaBusy((m) => ({ ...m, [key]: false }));
    }
  };

  const hasOpeningTurn = p.turns.some((t) => t.index === 0);
  const lastTurn = p.turns[p.turns.length - 1];
  const latestKey = p.live ? "live" : lastTurn ? lastTurn.id : "opening";

  const media = (list: Asset[], autoPlay = false) => {
    // newest first (v1.2: the opening may get a newer image/audio pair after enrichment)
    const byNew = [...list].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    const img = byNew.find((a) => a.type === "image");
    const aud = byNew.find((a) => a.type === "audio");
    return (
      <>
        {img ? <Illustration asset={img} onReplace={replaceAsset} /> : null}
        {aud ? (
          <AudioBar asset={aud} autoPlay={autoPlay && prefs.autoVoice} onReplace={replaceAsset} />
        ) : null}
      </>
    );
  };

  const exportSave = async () => {
    try {
      const save = await api.exportSave(id);
      downloadBlob(
        new Blob([JSON.stringify(save, null, 2)], { type: "application/json" }),
        `织梦存档-${world.title}-${new Date().toISOString().slice(0, 10)}.json`,
      );
      toast("存档已导出");
    } catch (e) {
      toast(`导出失败：${errorText(e)}`);
    }
  };

  const speak = (t: Turn) =>
    withBusy(`${t.id}:audio`, async () => {
      try {
        replaceAsset(await api.tts(id, { text: t.narration.slice(0, 600), turn_id: t.id }));
      } catch (e) {
        toast(`配音失败：${errorText(e)}`);
      }
    });
  const illustrate = (t: Turn) =>
    withBusy(`${t.id}:image`, async () => {
      try {
        replaceAsset(await api.illustrate(id, { turn_id: t.id }));
      } catch (e) {
        toast(`插画生成失败：${errorText(e)}`);
      }
    });

  const renderTurn = (t: Turn, i: number) => {
    const prev = i > 0 ? p.turns[i - 1] : null;
    const isLatest = t.id === lastTurn?.id && !p.live;
    const chapterBreak = !prev ? t.chapter > 1 || hasOpeningTurn : prev.chapter !== t.chapter;
    return (
      <Fragment key={t.id}>
        {chapterBreak && t.index !== 0 ? <div className="chapter-mark">第 {t.chapter} 章</div> : null}
        <article
          className="turn"
          data-testid={isLatest ? "narration-latest" : "narration-turn"}
          data-turn={t.index}
        >
          {t.index !== 0 && t.action ? (
            <div className="turn-action">
              <span>{t.action}</span>
            </div>
          ) : null}
          <p className="narr">{t.narration}</p>
          {media(assetsFor(t.id, isLatest))}
          <div className="turn-meta">
            <AiLabel text={t.ai_label} />
            {t.source === "fallback" ? (
              <span className="tag" title="大模型暂不可用，本回合由本地叙事模板生成">
                本地叙事
              </span>
            ) : null}
            <span>
              第{t.chapter}章 · 第{t.index}回合
            </span>
            {t.key_scene ? <span className="tag rose">关键场景</span> : null}
            <span className="spacer" />
            <button
              type="button"
              className="linkish"
              onClick={() => void speak(t)}
              disabled={mediaBusy[`${t.id}:audio`]}
              title="为这段生成配音"
            >
              <Volume2 size={12} aria-hidden /> {mediaBusy[`${t.id}:audio`] ? "配音请求中…" : "朗读"}
            </button>
            <button
              type="button"
              className="linkish"
              onClick={() => void illustrate(t)}
              disabled={mediaBusy[`${t.id}:image`]}
              title="为这段生成插画"
            >
              <ImageIcon size={12} aria-hidden /> {mediaBusy[`${t.id}:image`] ? "构图中…" : "配图"}
            </button>
            {isLatest && t.index > 0 ? (
              <button
                type="button"
                className="linkish"
                data-testid="rewrite-btn"
                onClick={p.rewriteLast}
                disabled={p.busy}
              >
                <RotateCcw size={12} aria-hidden /> 重写本回合
              </button>
            ) : null}
            <button
              type="button"
              className="linkish"
              data-testid="report-turn-btn"
              onClick={() => setReport({ turnId: t.id, content: t.narration })}
            >
              <Flag size={12} aria-hidden /> 举报此段
            </button>
          </div>
        </article>
      </Fragment>
    );
  };

  return (
    <div className="play-page">
      {memoryOpen ? (
        <aside className="drawer card" aria-label="世界记忆">
          <div className="card-h">
            <Brain size={16} aria-hidden />
            <h2 className="h2">世界记忆</h2>
            <Link href={`/memory/${id}`} className="linkish">
              完整记忆库 →
            </Link>
            <button
              type="button"
              className="icon-btn"
              aria-label="收起记忆"
              onClick={() => setMemoryOpen(false)}
            >
              ×
            </button>
          </div>
          <MemoryQuery key={memoryQ ?? ""} worldId={id} initialQuestion={memoryQ} />
        </aside>
      ) : null}

      <div className="play">
        <div className="play-main">
          <section className="card story">
            <header className="story-head">
              <h1 className="h1">{world.title}</h1>
              <span className="tag gold">
                第{world.state.chapter}章 · 第{world.state.turn}回合
              </span>
              {world.state.time ? <span className="tag">{world.state.time}</span> : null}
              {world.mode === "education" ? <span className="tag jade">教育模式</span> : null}
              {world.minor_mode ? <span className="tag jade">未成年人模式</span> : null}
              <AiLabel text={world.ai_label} />
              <div className="toolbar" role="toolbar" aria-label="世界工具">
                <button
                  type="button"
                  className="btn sm ghost"
                  data-testid="memory-tab"
                  onClick={() => setMemoryOpen(true)}
                >
                  <Brain size={14} aria-hidden /> 世界记忆
                </button>
                <Link href={`/god/${id}`} className="btn sm ghost" data-testid="god-view-btn">
                  <Eye size={14} aria-hidden /> 上帝视角
                </Link>
                {world.mode === "education" ? (
                  <button
                    type="button"
                    className="btn sm ghost"
                    data-testid="edu-summary-btn"
                    onClick={() => setEduOpen(true)}
                  >
                    <GraduationCap size={14} aria-hidden /> 学习小结
                  </button>
                ) : null}
                <button
                  type="button"
                  className="btn sm ghost"
                  data-testid="export-btn"
                  onClick={() => void exportSave()}
                >
                  <Download size={14} aria-hidden /> 导出存档
                </button>
                <button
                  type="button"
                  className="btn sm ghost"
                  data-testid="poster-btn"
                  onClick={() => setPosterOpen(true)}
                >
                  <Share2 size={14} aria-hidden /> 海报
                </button>
                <button
                  type="button"
                  className="btn sm danger"
                  data-testid="report-btn"
                  onClick={() =>
                    setReport({
                      turnId: lastTurn?.id,
                      content: p.live?.text || lastTurn?.narration || world.opening_scene,
                    })
                  }
                >
                  <Flag size={14} aria-hidden /> 举报
                </button>
              </div>
            </header>

            {world.status === "draft" ? (
              <div className="notice info row">
                <span style={{ flex: 1 }}>这个世界还是草稿。</span>
                <Link className="btn sm" href={`/preview/${id}`}>
                  去预览并确认
                </Link>
              </div>
            ) : null}

            <div className="narration" data-testid="narration" aria-live="polite">
              {!hasOpeningTurn ? (
                <article
                  className="turn opening"
                  data-testid={latestKey === "opening" ? "narration-latest" : "narration-turn"}
                >
                  <div className="chapter-mark">序 章</div>
                  <p className="narr">{world.opening_scene || world.premise}</p>
                  {media(assetsFor(null, latestKey === "opening"), true)}
                  <div className="turn-meta">
                    <AiLabel text={world.ai_label} />
                    <span>开场</span>
                  </div>
                </article>
              ) : null}
              {p.turns.map(renderTurn)}
              {p.live ? (
                <article className="turn live" data-testid="narration-latest">
                  {!p.live.rewrite ? (
                    <div className="turn-action">
                      <span>{p.live.action}</span>
                    </div>
                  ) : (
                    <div className="faint" style={{ fontSize: 12 }}>
                      正在重写上一回合…
                    </div>
                  )}
                  {p.live.facts.length ? (
                    <div className="memory-chips" aria-label="本回合调取的记忆">
                      {p.live.facts.slice(0, 4).map((f) => (
                        <span key={f.fact_id} className="memory-chip" title={f.content}>
                          忆 · {f.source} · {f.content}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {p.live.events.filter((e) => e.type !== "player").length ? (
                    <div className="memory-chips">
                      {p.live.events
                        .filter((e) => e.type !== "player")
                        .slice(0, 3)
                        .map((e) => (
                          <span key={e.id} className="memory-chip rose">
                            此刻，别处 · {e.summary}
                          </span>
                        ))}
                    </div>
                  ) : null}
                  {p.live.fallback ? (
                    <div className="faint" style={{ fontSize: 12 }} data-testid="narration-fallback">
                      模型连接中断，已改由本地叙事模板重新讲述本回合
                    </div>
                  ) : null}
                  <p className="narr live">
                    {p.live.text}
                    <span className="caret" aria-hidden />
                  </p>
                  {media(
                    p.assets.filter((a) => a.turn_id && !turnIds.has(a.turn_id)),
                    true,
                  )}
                </article>
              ) : null}
              <div ref={endRef} />
            </div>

            {p.busy ? (
              <div className="thinking" data-testid="thinking-indicator">
                <Loom compact stages={TURN_STAGES} progress={p.live?.progress ?? null} />
              </div>
            ) : null}

            {p.safety && (p.safety.blocked || p.safety.crisis) ? (
              <SafetyNotice result={p.safety} onClose={p.dismissSafety} />
            ) : p.safety && !p.busy && (p.safety.categories?.length || p.safety.filtered_text) ? (
              <div className="notice info" role="status" data-testid="safety-filtered">
                本回合部分内容已按「{p.safety.rating}」分级过滤或改写。{p.safety.message ?? ""}
              </div>
            ) : null}
            {p.error && !p.busy ? (
              <div className="notice warn row" role="alert">
                <span style={{ flex: 1 }}>{p.error.message}</span>
                {p.pending ? (
                  <button type="button" className="btn sm" data-testid="retry-btn" onClick={p.retry}>
                    <RotateCcw size={14} aria-hidden /> 重试
                  </button>
                ) : null}
                <button type="button" className="linkish" onClick={p.dismissError}>
                  放弃
                </button>
              </div>
            ) : null}

            <div className="play-controls">
              <form
                className="composer-bar"
                onSubmit={(e) => {
                  e.preventDefault();
                  submit();
                }}
              >
                <textarea
                  ref={inputRef}
                  className="textarea"
                  data-testid="free-input"
                  placeholder="你想做什么？输入你的行动…"
                  value={input}
                  maxLength={300}
                  rows={1}
                  disabled={p.busy}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      submit();
                    }
                  }}
                  aria-label="自由行动"
                />
                <button
                  type="submit"
                  className="btn"
                  data-testid="send-btn"
                  disabled={p.busy || !input.trim()}
                >
                  <Send size={16} aria-hidden /> 行动
                </button>
              </form>
              {p.options.length ? (
                <div className="options" aria-label="可选行动">
                  {p.options.map((o, i) => (
                    <button
                      key={o.id}
                      type="button"
                      className="option"
                      data-testid="option-btn"
                      disabled={p.busy}
                      onClick={() => p.send(o.text, o.id)}
                      style={{ animationDelay: `${i * 60}ms` }}
                    >
                      <span className="num">{String(i + 1).padStart(2, "0")}</span>
                      <span>
                        {o.text}
                        {o.hint ? <small>{o.hint}</small> : null}
                      </span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </section>
        </div>

        <aside className="play-side" aria-label="世界面板">
          <GenUI
            components={p.ui}
            handlers={handlers}
            streaming={p.busy}
            source={p.uiSource}
            // v1.2: event_feed / choice_list are area:"bottom" — mirrored by the 场外大事件 panel and the
            // option buttons, so the side panel skips that area (type list kept for older servers).
            skipAreas={["bottom"]}
            exclude={["event_feed", "choice_list"]}
          />
          <OffscreenPanel world={world} events={p.events} />
        </aside>
      </div>

      {report ? (
        <ReportDialog
          worldId={id}
          turnId={report.turnId}
          content={report.content}
          onClose={() => setReport(null)}
        />
      ) : null}
      {posterOpen ? (
        <PosterDialog world={world} assets={p.assets} onClose={() => setPosterOpen(false)} />
      ) : null}
      {eduOpen ? <EduSummaryDialog worldId={id} onClose={() => setEduOpen(false)} /> : null}
    </div>
  );
}
