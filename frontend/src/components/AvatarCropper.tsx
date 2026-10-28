"use client";
/**
 * Square avatar crop before upload: drag to move, slider / wheel to zoom; exports 512×512 (webp, else png).
 * The server re-crops to 256×256 webp anyway — this only lets the user choose the framing.
 */
import { useEffect, useRef, useState, type PointerEvent } from "react";
import { Dialog } from "./Dialog";

const VIEW = 240;
const OUT = 512;

export function AvatarCropper({
  file,
  onCancel,
  onDone,
  busy,
}: {
  file: File;
  onCancel: () => void;
  onDone: (blob: Blob, name: string) => void;
  busy?: boolean;
}) {
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null);

  useEffect(() => {
    let live = true;
    const url = URL.createObjectURL(file);
    const im = new Image();
    im.onload = () => live && setImg(im);
    im.onerror = () => live && setErr("图片无法识别，请换一张 PNG、JPG 或 WebP 图片");
    im.src = url;
    return () => {
      live = false;
      // revoke after the browser has had a chance to decode (the <img> preview reuses this URL)
      setTimeout(() => URL.revokeObjectURL(url), 0);
    };
  }, [file]);

  // the image always covers the square: base scale = cover, then × zoom
  const base = img ? VIEW / Math.min(img.naturalWidth, img.naturalHeight) : 1;
  const w = img ? img.naturalWidth * base * zoom : VIEW;
  const h = img ? img.naturalHeight * base * zoom : VIEW;
  const clamp = (p: { x: number; y: number }, ww = w, hh = h) => ({
    x: Math.min(0, Math.max(VIEW - ww, p.x)),
    y: Math.min(0, Math.max(VIEW - hh, p.y)),
  });
  // centre on load / keep the centre while zooming
  const off = clamp(img && pos.x === 0 && pos.y === 0 && zoom === 1 ? { x: (VIEW - w) / 2, y: (VIEW - h) / 2 } : pos);

  const setZoomKeep = (z: number) => {
    const nz = Math.min(3, Math.max(1, z));
    if (!img) return setZoom(nz);
    const cx = (VIEW / 2 - off.x) / w;
    const cy = (VIEW / 2 - off.y) / h;
    const nw = img.naturalWidth * base * nz;
    const nh = img.naturalHeight * base * nz;
    setZoom(nz);
    setPos(clamp({ x: VIEW / 2 - cx * nw, y: VIEW / 2 - cy * nh }, nw, nh));
  };

  const down = (e: PointerEvent<HTMLDivElement>) => {
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, px: off.x, py: off.y };
  };
  const move = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    setPos(clamp({ x: d.px + e.clientX - d.x, y: d.py + e.clientY - d.y }));
  };

  const save = () => {
    if (!img) return;
    const c = document.createElement("canvas");
    c.width = c.height = OUT;
    const ctx = c.getContext("2d");
    if (!ctx) return setErr("当前浏览器无法处理图片，请换个浏览器再试");
    const k = OUT / VIEW;
    ctx.drawImage(img, off.x * k, off.y * k, w * k, h * k);
    c.toBlob(
      (b) => {
        if (b && b.type === "image/webp") return onDone(b, "avatar.webp");
        c.toBlob((p) => (p ? onDone(p, "avatar.png") : setErr("图片处理失败，请重试")), "image/png");
      },
      "image/webp",
      0.9,
    );
  };

  return (
    <Dialog title="调整头像" onClose={onCancel} testId="avatar-crop">
      <div className="stack" style={{ alignItems: "center" }}>
        {err ? (
          <div className="notice warn" role="alert" data-testid="avatar-crop-error">
            {err}
          </div>
        ) : (
          <div
            className="crop-view"
            style={{ width: VIEW, height: VIEW }}
            onPointerDown={down}
            onPointerMove={move}
            onPointerUp={() => (drag.current = null)}
            onPointerCancel={() => (drag.current = null)}
            onWheel={(e) => setZoomKeep(zoom - e.deltaY / 500)}
            data-testid="avatar-crop-view"
          >
            {img ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={img.src} alt="头像预览" draggable={false} style={{ width: w, height: h, left: off.x, top: off.y }} />
            ) : (
              <div className="skel" style={{ width: "100%", height: "100%" }} />
            )}
          </div>
        )}
        <label className="row" style={{ width: VIEW, gap: 8, fontSize: 13 }}>
          <span className="faint">缩放</span>
          <input
            type="range"
            min={1}
            max={3}
            step={0.01}
            value={zoom}
            style={{ flex: 1 }}
            aria-label="缩放"
            data-testid="avatar-zoom"
            onChange={(e) => setZoomKeep(Number(e.target.value))}
          />
        </label>
        <p className="faint" style={{ fontSize: 12, margin: 0 }}>
          拖动图片选择显示区域，圆形内为头像效果。
        </p>
        <div className="row" style={{ justifyContent: "flex-end", alignSelf: "stretch" }}>
          <button type="button" className="btn ghost" onClick={onCancel} data-testid="avatar-crop-cancel">
            取消
          </button>
          <button
            type="button"
            className="btn"
            disabled={!img || !!err || busy}
            onClick={save}
            data-testid="avatar-crop-save"
          >
            {busy ? "正在上传…" : "保存头像"}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
