"use client";
/** F8 结局海报 (GET /poster, local fallback) + PNG download + ending short video (WebM). */
import { useEffect, useRef, useState } from "react";
import { Download, Film } from "lucide-react";
import { toPng } from "html-to-image";
import { api, assetUrl, errorText } from "@/lib/api";
import type { Asset, Poster, World } from "@/lib/types";
import { canRecordVideo, downloadBlob, recordEndingVideo } from "@/lib/video";
import { Dialog } from "./Dialog";
import { AI_LABEL, SHOW_AI_LABEL } from "./AiLabel";
import { useToast } from "./Toast";

const POSTER_BG = "#12162a";

function localPoster(world: World, assets: Asset[]): Poster {
  return {
    title: world.title,
    subtitle: [world.era, world.genre].filter(Boolean).join(" · "),
    tagline: world.premise.slice(0, 40),
    summary: world.initial_conflict,
    ending: null,
    characters: world.characters
      .slice(0, 6)
      .map((c) => ({ name: c.name, role: c.role, emoji: c.avatar_emoji ?? "" })),
    stats: { turns: world.state.turn, chapters: world.state.chapter, events: 0 },
    image_url: assets.find((a) => a.type === "image")?.url ?? null,
    theme: { primary: "#f1d59a", secondary: "#d66d7f", background: POSTER_BG },
    qr_text: typeof window !== "undefined" ? window.location.origin : "",
    ai_label: world.ai_label || AI_LABEL,
    safety_label: "已通过内容安全审核",
    rating: world.rating,
  };
}

export function PosterDialog({
  world,
  assets,
  onClose,
}: {
  world: World;
  assets: Asset[];
  onClose: () => void;
}) {
  const toast = useToast();
  const [poster, setPoster] = useState<Poster | null>(null);
  const [recording, setRecording] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    api
      .poster(world.id)
      // a partial / malformed server poster falls back field-by-field to the local one
      .then((p) => {
        const local = localPoster(world, assets);
        setPoster(
          p && typeof p === "object" && !Array.isArray(p)
            ? { ...local, ...p, characters: Array.isArray(p.characters) ? p.characters : local.characters }
            : local,
        );
      })
      .catch(() => setPoster(localPoster(world, assets)));
  }, [world, assets]);

  const savePng = async () => {
    if (!ref.current) return;
    try {
      // export as a solid, square-cornered card: no transparent rounded corners / drop shadow in the PNG
      const url = await toPng(ref.current, {
        pixelRatio: 2,
        cacheBust: true,
        backgroundColor: poster?.theme?.background || POSTER_BG,
        style: { borderRadius: "0", boxShadow: "none", margin: "0" },
      });
      const a = document.createElement("a");
      a.href = url;
      a.download = `织梦-${world.title}-海报.png`;
      a.click();
    } catch (e) {
      toast(`海报导出失败：${errorText(e)}`);
    }
  };
  const saveVideo = async () => {
    if (!poster) return;
    if (!canRecordVideo()) return toast("当前浏览器不支持录制短视频，请使用新版 Chrome / Edge");
    setRecording(true);
    try {
      const blob = await recordEndingVideo(poster, poster.image_url ? assetUrl(poster.image_url) : null);
      downloadBlob(blob, `织梦-${world.title}-结局.webm`);
    } catch (e) {
      toast(`短视频生成失败：${errorText(e)}`);
    } finally {
      setRecording(false);
    }
  };

  return (
    <Dialog title="结局海报 · 分享" onClose={onClose} wide>
      <div className="poster-wrap">
        {poster ? (
          <div
            ref={ref}
            className="poster"
            data-testid="poster"
            style={{ ["--poster-bg" as string]: poster.theme?.background, color: "#f6efe2" }}
          >
            {poster.image_url ? (
              <div className="poster-img" style={{ backgroundImage: `url(${assetUrl(poster.image_url)})` }} />
            ) : null}
            <div className="poster-scrim" aria-hidden />
            <div className="p-eyebrow">织 梦 · 我 的 世 界</div>
            <h3 className="p-title" style={{ color: poster.theme?.primary }}>
              {poster.title}
            </h3>
            <div className="p-tag">{poster.tagline || poster.subtitle}</div>
            <p className="p-sum">{poster.ending || poster.summary}</p>
            <div className="p-chars">
              {poster.characters.map((c) => (
                <span key={c.name}>
                  {c.emoji} {c.name}
                </span>
              ))}
            </div>
            <div className="p-foot">
              <div>
                <div>
                  {poster.stats.turns} 回合 · {poster.stats.chapters} 章 · {poster.stats.events} 场外事件
                </div>
                <div>
                  {SHOW_AI_LABEL
                    ? `${poster.ai_label || AI_LABEL} · ${poster.safety_label} · 分级 ${poster.rating}`
                    : `分级 ${poster.rating}`}
                </div>
              </div>
              <div style={{ textAlign: "right", maxWidth: 120, wordBreak: "break-all" }}>
                {poster.qr_text}
              </div>
            </div>
          </div>
        ) : (
          <div className="poster skel" />
        )}
        <div className="stack poster-actions">
          <p className="muted" style={{ margin: 0 }}>
            {SHOW_AI_LABEL
              ? `海报与短视频均附带「${AI_LABEL}」与内容安全标识，可放心分享。`
              : "保存海报或导出结局短视频，留住这段旅程。"}
          </p>
          <button
            type="button"
            className="btn"
            data-testid="poster-download"
            disabled={!poster}
            onClick={() => void savePng()}
          >
            <Download size={16} aria-hidden /> 保存海报 PNG
          </button>
          <button
            type="button"
            className="btn ghost"
            data-testid="video-btn"
            disabled={!poster || recording}
            onClick={() => void saveVideo()}
          >
            <Film size={16} aria-hidden /> {recording ? "正在织就短视频…" : "导出结局短视频"}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
