"use client";
/** F5: scene illustration + narration audio, with manual regenerate. */
import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api, assetUrl } from "@/lib/api";
import type { Asset } from "@/lib/types";
import { AiLabel } from "./AiLabel";

export function Illustration({ asset, onReplace }: { asset: Asset; onReplace?: (a: Asset) => void }) {
  const [busy, setBusy] = useState(false);
  const regen = async () => {
    setBusy(true);
    try {
      onReplace?.(await api.regenerateAsset(asset.id));
    } catch {
      /* keep old one */
    } finally {
      setBusy(false);
    }
  };
  return (
    <figure className="scene-img">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={assetUrl(asset.url)}
        alt={asset.prompt || "场景插画"}
        data-testid="illustration"
        loading="lazy"
      />
      <figcaption>
        <AiLabel testId="ai-label-image" />
        {asset.source === "fallback" ? <span className="ai-label muted-label">占位插画</span> : null}
        {onReplace ? (
          <button
            type="button"
            className="ai-label as-btn"
            onClick={() => void regen()}
            disabled={busy}
            data-testid="regen-image-btn"
          >
            <RefreshCw size={11} aria-hidden /> {busy ? "重绘中" : "重绘"}
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
  useEffect(() => {
    if (autoPlay) ref.current?.play().catch(() => {});
  }, [autoPlay, asset.url]);
  return (
    <div className="audio-bar">
      <span className="faint" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
        旁白{asset.source === "fallback" ? "（占位）" : ""}
      </span>
      <audio ref={ref} controls preload="none" src={assetUrl(asset.url)} data-testid="audio-player" />
      {onReplace ? (
        <button
          type="button"
          className="icon-btn"
          aria-label="重新配音"
          onClick={() =>
            void api
              .regenerateAsset(asset.id)
              .then(onReplace)
              .catch(() => {})
          }
        >
          <RefreshCw size={13} />
        </button>
      ) : null}
    </div>
  );
}
