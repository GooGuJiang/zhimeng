"use client";
/**
 * F5: scene illustration + narration audio, with manual regenerate.
 * v1.3: assets upgrade in place (same id, new url). Images cross-fade to the new file once it has
 * loaded; audio swaps its source only when it isn't playing (otherwise after it ends / on next play).
 * `pending` shows an in-progress state; `ready` + `fallback` is a final placeholder with a retry entry.
 */
import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api, assetUrl } from "@/lib/api";
import { isFinalPlaceholder, isPending } from "@/lib/assets";
import type { Asset } from "@/lib/types";
import { AiLabel } from "./AiLabel";

function useRegenerate(asset: Asset, onReplace?: (a: Asset) => void) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const run = async () => {
    setBusy(true);
    setFailed(false);
    try {
      // answers within ~8 s; may be a pending placeholder that the parent keeps long-polling
      onReplace?.(await api.regenerateAsset(asset.id));
    } catch {
      setFailed(true); // keep the current one on screen
    } finally {
      setBusy(false);
    }
  };
  return { busy, failed, run };
}

export function Illustration({ asset, onReplace }: { asset: Asset; onReplace?: (a: Asset) => void }) {
  const src = assetUrl(asset.url);
  // `shown` lags behind `src` until the new file has loaded, then the new layer fades in on top.
  const [shown, setShown] = useState(src);
  const [prev, setPrev] = useState<string | null>(null);
  useEffect(() => {
    if (src === shown) return;
    let live = true;
    const img = new Image();
    const swap = () => {
      if (!live) return;
      setPrev(shown);
      setShown(src);
    };
    img.onload = swap;
    img.onerror = swap; // let the <img> show its own broken state rather than keep a stale one forever
    img.src = src;
    return () => {
      live = false;
    };
  }, [src, shown]);
  const regen = useRegenerate(asset, onReplace);
  const pending = isPending(asset);
  const finalPh = isFinalPlaceholder(asset);
  return (
    <figure className={`scene-img${pending ? " is-pending" : ""}`} data-status={asset.status ?? "ready"}>
      {prev ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={prev} alt="" aria-hidden className="scene-img-prev" />
      ) : null}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        key={shown}
        src={shown}
        alt={asset.prompt || "场景插画"}
        data-testid="illustration"
        data-version={asset.version ?? 1}
        className={prev ? "scene-img-fade" : undefined}
        onAnimationEnd={() => setPrev(null)}
        loading="lazy"
      />
      {pending ? (
        <div className="scene-img-status" data-testid="illustration-pending" role="status">
          <span className="dots" aria-hidden>
            <i />
            <i />
            <i />
          </span>
          精绘中，先以草图示意…
        </div>
      ) : null}
      <figcaption>
        <AiLabel testId="ai-label-image" />
        {finalPh ? (
          <span className="ai-label muted-label" data-testid="illustration-placeholder">
            占位插画（真实绘制未成功）
          </span>
        ) : null}
        {regen.failed ? <span className="ai-label muted-label">重绘失败，请稍后再试</span> : null}
        {onReplace && !pending ? (
          <button
            type="button"
            className="ai-label as-btn"
            onClick={() => void regen.run()}
            disabled={regen.busy}
            data-testid="regen-image-btn"
          >
            <RefreshCw size={11} aria-hidden /> {regen.busy ? "重绘中" : finalPh ? "重新生成" : "重绘"}
          </button>
        ) : null}
      </figcaption>
    </figure>
  );
}

export function AudioBar({
  asset,
  autoPlay,
  onReplace,
}: {
  asset: Asset;
  autoPlay?: boolean;
  onReplace?: (a: Asset) => void;
}) {
  const ref = useRef<HTMLAudioElement>(null);
  const url = assetUrl(asset.url);
  const pending = isPending(asset);
  const finalPh = isFinalPlaceholder(asset);
  const [src, setSrc] = useState(url);
  const queued = useRef<string | null>(null); // upgraded url waiting for the current playback to finish
  const autoPlayed = useRef(false);

  useEffect(() => {
    if (url === src) return;
    const el = ref.current;
    if (el && !el.paused && !el.ended) queued.current = url;
    else setSrc(url); // sync to an upgraded asset
  }, [url, src]);

  // auto-play once per asset, and only the real voice (not the silent pending placeholder)
  useEffect(() => {
    if (!autoPlay || pending || autoPlayed.current) return;
    autoPlayed.current = true;
    ref.current?.play().catch(() => {});
  }, [autoPlay, pending, src]);

  const takeQueued = () => {
    if (!queued.current) return false;
    const next = queued.current;
    queued.current = null;
    setSrc(next);
    return true;
  };
  const regen = useRegenerate(asset, onReplace);

  return (
    <div className="audio-bar" data-status={asset.status ?? "ready"}>
      <span className="faint" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
        旁白{finalPh ? "（占位）" : ""}
      </span>
      {pending ? (
        <span className="audio-pending" data-testid="audio-pending" role="status">
          <span className="dots" aria-hidden>
            <i />
            <i />
            <i />
          </span>
          配音生成中…
        </span>
      ) : null}
      <audio
        ref={ref}
        controls
        preload="none"
        src={src}
        data-testid="audio-player"
        data-version={asset.version ?? 1}
        hidden={pending}
        onEnded={() => void takeQueued()}
        onPlay={(e) => {
          // a newer version arrived while paused mid-way: start the new one instead
          if (queued.current && e.currentTarget.currentTime > 0 && takeQueued())
            requestAnimationFrame(() => ref.current?.play().catch(() => {}));
        }}
      />
      {onReplace && !pending ? (
        <button
          type="button"
          className="icon-btn"
          aria-label={finalPh ? "重新生成配音" : "重新配音"}
          title={finalPh ? "真实配音未成功，点此重新生成" : "重新配音"}
          data-testid="regen-audio-btn"
          disabled={regen.busy}
          onClick={() => void regen.run()}
        >
          <RefreshCw size={13} className={regen.busy ? "spin" : undefined} />
        </button>
      ) : null}
    </div>
  );
}
