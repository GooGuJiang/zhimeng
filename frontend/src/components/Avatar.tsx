"use client";
/**
 * User avatar: an uploaded image (`avatar_url` = "/api/static/avatars/…"), a built-in ink-seal preset
 * (`avatar_url` = "preset:<key>", contract §13.5 — the backend accepts any `[A-Za-z0-9_-]{1,32}` key, the list
 * below is ours), or the nickname's first character.
 */
import { useState } from "react";
import { assetUrl } from "@/lib/api";

export const AVATAR_PRESETS = [
  { key: "moon", glyph: "月", bg: "#356297", label: "明月" },
  { key: "bamboo", glyph: "竹", bg: "#2b7259", label: "修竹" },
  { key: "boat", glyph: "舟", bg: "#9a6322", label: "孤舟" },
  { key: "crane", glyph: "鹤", bg: "#a8424f", label: "仙鹤" },
  { key: "cloud", glyph: "云", bg: "#7d4a86", label: "流云" },
  { key: "hill", glyph: "山", bg: "#2a7078", label: "远山" },
  { key: "lamp", glyph: "灯", bg: "#b0372a", label: "灯火" },
  { key: "ink", glyph: "墨", bg: "#2b2620", label: "浓墨" },
] as const;
export const presetValue = (key: string) => `preset:${key}`;
const presetOf = (v: string | null | undefined) =>
  v?.startsWith("preset:") ? AVATAR_PRESETS.find((p) => presetValue(p.key) === v) : undefined;

const PALETTE = AVATAR_PRESETS.map((p) => p.bg);
const hash = (s: string) => [...s].reduce((h, c) => (h * 31 + c.codePointAt(0)!) >>> 0, 7);

export function Avatar({
  src,
  name,
  size = 32,
  testId,
}: {
  src: string | null | undefined;
  name: string;
  size?: number;
  testId?: string;
}) {
  const [broken, setBroken] = useState<string | null>(null);
  const style = { width: size, height: size, fontSize: Math.round(size * 0.46) };
  const preset = presetOf(src);
  if (src && !src.startsWith("preset:") && broken !== src)
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        className="avatar"
        src={assetUrl(src)}
        alt=""
        style={style}
        data-testid={testId}
        onError={() => setBroken(src)}
      />
    );
  const glyph = preset?.glyph ?? ([...name.trim()][0] || "梦");
  return (
    <span
      className="avatar seal"
      style={{ ...style, background: preset?.bg ?? PALETTE[hash(name || "梦") % PALETTE.length] }}
      aria-hidden
      data-testid={testId}
    >
      {glyph}
    </span>
  );
}
