/**
 * F8 结局短视频: renders an animated ending card on a <canvas> and records it with MediaRecorder
 * (WebM). Pure client-side, no upload. AI + safety labels are burned into every frame.
 */
import type { Poster } from "./types";

function wrap(ctx: CanvasRenderingContext2D, text: string, maxW: number): string[] {
  const lines: string[] = [];
  let cur = "";
  for (const ch of text) {
    if (ch === "\n") {
      lines.push(cur);
      cur = "";
      continue;
    }
    if (ctx.measureText(cur + ch).width > maxW) {
      lines.push(cur);
      cur = ch;
    } else cur += ch;
  }
  if (cur) lines.push(cur);
  return lines;
}

function loadImage(src: string | null): Promise<HTMLImageElement | null> {
  if (!src) return Promise.resolve(null);
  return new Promise((res) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => res(img);
    img.onerror = () => res(null);
    img.src = src;
  });
}

export function canRecordVideo() {
  return (
    typeof window !== "undefined" && "MediaRecorder" in window && !!HTMLCanvasElement.prototype.captureStream
  );
}

export async function recordEndingVideo(p: Poster, imageSrc: string | null, seconds = 6): Promise<Blob> {
  const W = 720;
  const H = 1280;
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d")!;
  const img = await loadImage(imageSrc);
  const serif = '"Noto Serif SC","Songti SC","STSong",serif';
  const sans = '"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif';
  const bg = p.theme?.background || "#12162a";
  const primary = p.theme?.primary || "#f1d59a";
  const secondary = p.theme?.secondary || "#d66d7f";

  const stream = canvas.captureStream(30);
  const mime =
    ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find((m) =>
      MediaRecorder.isTypeSupported(m),
    ) ?? "";
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: 2_500_000 } : undefined);
  const chunks: Blob[] = [];
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const done = new Promise<Blob>((res) => (rec.onstop = () => res(new Blob(chunks, { type: "video/webm" }))));

  const total = seconds * 1000;
  const t0 = performance.now();
  const ease = (x: number) => 1 - Math.pow(1 - Math.max(0, Math.min(1, x)), 3);

  const frame = () => {
    const t = performance.now() - t0;
    const k = t / total;
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);
    if (img) {
      const s = 1.08 - 0.08 * k; // slow Ken Burns
      const iw = W * s;
      const ih = (img.height / img.width) * iw;
      ctx.globalAlpha = 0.6;
      ctx.drawImage(img, (W - iw) / 2, 0, iw, Math.max(ih, H * 0.6));
      ctx.globalAlpha = 1;
    }
    const g = ctx.createLinearGradient(0, H * 0.25, 0, H);
    g.addColorStop(0, "rgba(0,0,0,0)");
    g.addColorStop(0.55, bg);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
    // threads
    ctx.strokeStyle = secondary;
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let x = 0; x <= W; x += 12) ctx.lineTo(x, 180 + Math.sin(x / 70 + t / 600) * 24);
    ctx.stroke();
    ctx.globalAlpha = 1;

    ctx.fillStyle = "rgba(246,239,226,0.75)";
    ctx.font = `22px ${sans}`;
    ctx.fillText("织 梦 · 我 的 世 界", 56, 110);

    const a1 = ease((t - 300) / 900);
    ctx.globalAlpha = a1;
    ctx.fillStyle = primary;
    ctx.font = `bold 64px ${serif}`;
    wrap(ctx, p.title, W - 112)
      .slice(0, 2)
      .forEach((l, i) => ctx.fillText(l, 56, 640 + i * 78 - (1 - a1) * 30));
    ctx.fillStyle = "#f6efe2";
    ctx.font = `28px ${serif}`;
    ctx.fillText(p.tagline || p.subtitle || "", 56, 820);
    ctx.globalAlpha = 1;

    const body = p.ending || p.summary || "";
    ctx.font = `24px ${serif}`;
    const lines = wrap(ctx, body, W - 112).slice(0, 8);
    const reveal = Math.floor(ease((t - 1400) / 3200) * body.length);
    let used = 0;
    ctx.fillStyle = "rgba(246,239,226,0.9)";
    lines.forEach((l, i) => {
      const show = l.slice(0, Math.max(0, reveal - used));
      used += l.length;
      ctx.fillText(show, 56, 880 + i * 38);
    });

    ctx.font = `20px ${sans}`;
    ctx.fillStyle = "rgba(246,239,226,0.7)";
    ctx.fillText(
      p.characters
        .map((c) => `${c.emoji ?? ""}${c.name}`)
        .join("  ")
        .slice(0, 40),
      56,
      1196,
    );
    ctx.fillStyle = "rgba(246,239,226,0.85)";
    ctx.fillText(
      `${p.ai_label || "内容由AI生成"} · ${p.safety_label || "已通过内容安全审核"} · 分级 ${p.rating}`,
      56,
      1236,
    );

    if (t < total) requestAnimationFrame(frame);
    else rec.stop();
  };
  rec.start(250);
  requestAnimationFrame(frame);
  return done;
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
