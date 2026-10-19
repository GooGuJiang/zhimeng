"use client";
/** 首页 / 造化开局 (F1): one sentence (or an uploaded text) → streamed world generation → preview. */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { BookOpen, FileText, Wand2, X } from "lucide-react";
import { api, streamPath } from "@/lib/api";
import type { GenerateWorldRequest, WorldSummary } from "@/lib/types";
import { useWorldGeneration } from "@/hooks/useWorldGeneration";
import { usePrefs } from "@/hooks/usePrefs";
import { useCurrentWorld } from "@/hooks/useCurrentWorld";
import { worldCache } from "@/lib/cache";
import { GenerationProgress } from "@/components/GenerationProgress";
import { SafetyNotice } from "@/components/SafetyNotice";
import { ImportSave } from "@/components/ImportSave";

const SEEDS = [
  "一个民国上海滩的侦探故事，我是报社记者",
  "末日后的长江航运，我是一艘渡船的船长",
  "盛唐长安的西市，我是刚到京城的胡商学徒",
  "海底图书馆里，书会在夜里偷偷改写结局",
];
const GENRES = ["悬疑", "武侠", "科幻", "奇幻", "历史", "日常", "恐怖"];
const TONES = ["沉郁", "轻快", "热血", "浪漫", "诡谲", "温情"];
const LENGTHS: { v: NonNullable<GenerateWorldRequest["length"]>; l: string }[] = [
  { v: "short", l: "短篇" },
  { v: "medium", l: "中篇" },
  { v: "long", l: "长篇" },
];

export function HomeView() {
  const router = useRouter();
  const gen = useWorldGeneration();
  const [prefs, setPrefs] = usePrefs();
  const [currentId] = useCurrentWorld();
  const [prompt, setPrompt] = useState("");
  const [genre, setGenre] = useState<string | null>(null);
  const [tone, setTone] = useState<string | null>(null);
  const [length, setLength] = useState<GenerateWorldRequest["length"]>("short");
  const [file, setFile] = useState<{ name: string; text: string } | null>(null);
  const [recent, setRecent] = useState<WorldSummary[]>([]);
  const [opening, setOpening] = useState(false);

  useEffect(() => {
    api
      .listWorlds()
      .then((ws) => setRecent(ws.slice(0, 6)))
      .catch(() => setRecent([]));
  }, []);

  const canGo = (prompt.trim().length > 0 || !!file) && !gen.running && !opening;

  const go = async () => {
    if (!canGo) return;
    const body: GenerateWorldRequest = {
      prompt: prompt.trim() || `根据上传的文本《${file?.name}》生成世界`,
      genre: genre ?? undefined,
      tone: tone ?? undefined,
      length,
      language: "zh",
      mode: "story",
      source_text: file?.text ?? null,
      minor_mode: prefs.minorMode,
      rating: prefs.minorMode ? "all" : "teen",
    };
    const t0 = Date.now();
    const { world, worldId } = await gen.run(streamPath.generate, body);
    if (world) worldCache.set(world);
    if (worldId) {
      setOpening(true); // keep the loom on screen while the preview route loads
      await new Promise((r) => setTimeout(r, Math.max(0, 700 - (Date.now() - t0))));
      router.push(`/preview/${worldId}`);
    }
  };

  const onUpload = async (f: File | undefined) => {
    if (!f) return;
    if (f.size > 200_000) return alert("文本过长（上限约 20 万字节），请截取片段");
    setFile({ name: f.name.replace(/\.[^.]+$/, ""), text: await f.text() });
  };

  return (
    <div className="home">
      <section className="hero">
        <div className="hero-copy">
          <div className="eyebrow">AI 原生互动叙事引擎</div>
          <h1 className="h-display">
            一句话，
            <br />
            织出一个<em>会呼吸</em>的世界
          </h1>
          <p className="lead">
            写下你想走进的故事。织梦会铺开地图、唤醒角色、埋下冲突——他们有自己的目标与记忆，在你转身时依然行动。
          </p>
          <div className="row">
            <Link href="/education" className="btn ghost" data-testid="education-entry">
              <BookOpen size={16} aria-hidden /> 教育模式
            </Link>
            {currentId ? (
              <Link href={`/play/${currentId}`} className="btn ghost">
                继续上次的世界
              </Link>
            ) : null}
          </div>
          <p className="hero-quote">经纬为骨 · 记忆为丝 · 众生自织</p>
        </div>

        <div className="composer card">
          <label className="field">
            <span>你的灵感</span>
            <textarea
              className="textarea big"
              data-testid="prompt-input"
              placeholder="用一句话描述你想走进的世界，例如：民国上海滩的侦探故事，我是报社记者"
              value={prompt}
              maxLength={500}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void go();
              }}
              disabled={gen.running}
            />
          </label>
          <div className="seed-list" aria-label="灵感示例">
            {SEEDS.map((s) => (
              <button
                key={s}
                type="button"
                className="seed"
                onClick={() => setPrompt(s)}
                disabled={gen.running}
              >
                {s}
              </button>
            ))}
          </div>

          <div className="opt-group">
            <span className="opt-label">题材</span>
            <div className="chips">
              {GENRES.map((g) => (
                <button
                  key={g}
                  type="button"
                  className={`chip${genre === g ? " on" : ""}`}
                  aria-pressed={genre === g}
                  onClick={() => setGenre(genre === g ? null : g)}
                >
                  {g}
                </button>
              ))}
            </div>
          </div>
          <div className="opt-group">
            <span className="opt-label">基调</span>
            <div className="chips">
              {TONES.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`chip${tone === t ? " on" : ""}`}
                  aria-pressed={tone === t}
                  onClick={() => setTone(tone === t ? null : t)}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
          <div className="opt-group">
            <span className="opt-label">篇幅</span>
            <div className="chips">
              {LENGTHS.map((l) => (
                <button
                  key={l.v}
                  type="button"
                  className={`chip${length === l.v ? " on" : ""}`}
                  aria-pressed={length === l.v}
                  onClick={() => setLength(l.v)}
                >
                  {l.l}
                </button>
              ))}
            </div>
          </div>

          <div className="composer-foot">
            <label className="upload">
              <FileText size={14} aria-hidden />
              {file ? `已载入《${file.name}》` : "上传设定 / 课文 (.txt)"}
              <input
                type="file"
                accept=".txt,.md,text/plain,text/markdown"
                className="sr-only"
                data-testid="source-upload"
                onChange={(e) => void onUpload(e.target.files?.[0])}
              />
            </label>
            {file ? (
              <button
                type="button"
                className="icon-btn"
                aria-label="移除上传文本"
                onClick={() => setFile(null)}
              >
                <X size={14} />
              </button>
            ) : null}
            <label className="switch">
              <input
                type="checkbox"
                data-testid="minor-mode-toggle"
                checked={prefs.minorMode}
                onChange={(e) => setPrefs({ minorMode: e.target.checked })}
              />
              未成年人模式
            </label>
            <span className="spacer" />
            <button
              type="button"
              className="btn lg"
              data-testid="generate-btn"
              disabled={!canGo}
              onClick={() => void go()}
            >
              <Wand2 size={18} aria-hidden /> 造化
            </button>
          </div>
          {gen.running || opening ? (
            <GenerationProgress
              gen={
                opening
                  ? { ...gen, progress: { stage: "memory", message: "世界已织就，正在展开…", pct: 100 } }
                  : gen
              }
            />
          ) : null}
          <p className="faint" style={{ fontSize: 12, margin: "12px 0 0" }}>
            生成内容由 AI 创作并经双向安全审核；未成年人模式下仅生成全年龄内容。
          </p>
        </div>
      </section>

      {gen.safety?.blocked || gen.safety?.crisis ? <SafetyNotice result={gen.safety} /> : null}
      {gen.error && !gen.running ? (
        <div className="notice warn row" role="alert">
          <span style={{ flex: 1 }}>{gen.error}（未保存任何内容）</span>
          <button type="button" className="btn sm ghost" data-testid="retry-btn" onClick={() => void go()}>
            重试
          </button>
        </div>
      ) : null}

      <section className="recent">
        <div className="card-h">
          <i className="knot" aria-hidden />
          <h2 className="h2">我的世界</h2>
          <ImportSave />
        </div>
        {recent.length ? (
          <div className="grid-3">
            {recent.map((w) => (
              <Link
                key={w.id}
                href={w.status === "draft" ? `/preview/${w.id}` : `/play/${w.id}`}
                className="world-tile"
              >
                <strong>{w.title}</strong>
                <span className="faint" style={{ fontSize: 13 }}>
                  {[w.mode === "education" ? "教育" : w.genre, w.tone].filter(Boolean).join(" · ")} · 第{" "}
                  {w.turn} 回合
                  {w.status === "draft" ? " · 草稿" : ""}
                </span>
              </Link>
            ))}
          </div>
        ) : (
          <p className="faint">还没有世界。写下第一句话吧。</p>
        )}
      </section>
    </div>
  );
}
