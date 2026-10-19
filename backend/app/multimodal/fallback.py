"""Offline placeholders: SVG illustration card and a short silent WAV."""
from __future__ import annotations

import hashlib
import html
import io
import struct
import textwrap
import wave

PALETTES = [("#1e1b4b", "#7c3aed", "#f5d0fe"), ("#0f172a", "#0ea5e9", "#e0f2fe"), ("#1c1917", "#d97706", "#fef3c7"),
            ("#052e16", "#16a34a", "#dcfce7"), ("#3f0d12", "#e11d48", "#ffe4e6"), ("#111827", "#6b7280", "#f3f4f6")]


def placeholder_svg(title: str, caption: str = "", label: str | None = None) -> bytes:
    if label is None:  # visible label only when ZM_SHOW_AI_LABEL=1 (user request); ai_meta is unaffected
        from app.safety.labels import show_visible_label

        label = "内容由AI生成 · 插画占位" if show_visible_label() else ""
    h = int(hashlib.sha256((title + caption).encode()).hexdigest(), 16)
    bg, accent, fg = PALETTES[h % len(PALETTES)]
    lines = textwrap.wrap(caption.replace("\n", " "), 26)[:4]
    cap = "".join(f'<text x="80" y="{430 + i * 44}" font-size="28" fill="{fg}" opacity="0.85">{html.escape(l)}</text>'
                  for i, l in enumerate(lines))
    # a few deterministic "stars" / mountains for atmosphere
    stars = "".join(f'<circle cx="{(h >> (i * 3)) % 1280}" cy="{(h >> (i * 5)) % 300}" r="{1 + (h >> i) % 3}" '
                    f'fill="{fg}" opacity="0.5"/>' for i in range(24))
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{bg}"/>
<stop offset="1" stop-color="{accent}"/></linearGradient></defs>
<rect width="1280" height="720" fill="url(#g)"/>{stars}
<path d="M0 560 L220 400 L380 500 L620 330 L860 520 L1040 420 L1280 540 L1280 720 L0 720 Z" fill="{bg}" opacity="0.55"/>
<text x="80" y="360" font-size="56" font-weight="bold" fill="{fg}" font-family="sans-serif">{html.escape(title[:24])}</text>
{cap}
{f'<text x="1200" y="690" font-size="20" fill="{fg}" opacity="0.7" text-anchor="end">{html.escape(label)}</text>' if label else ""}
</svg>"""
    return svg.encode("utf-8")


def silent_wav(seconds: float = 0.5, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(seconds * rate))
    return buf.getvalue()


def fix_wav_header(data: bytes) -> bytes:
    """Qwen-TTS WAVs may carry streaming placeholder sizes (0xFFFFFFFF / 0) in the RIFF and ``data`` chunk
    headers, which makes browsers show a bogus duration. Rewrite both sizes from the actual byte length."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data
    buf = bytearray(data)
    pos = 12
    while pos + 8 <= len(buf):
        cid = bytes(buf[pos:pos + 4])
        size = struct.unpack("<I", buf[pos + 4:pos + 8])[0]
        if cid == b"data":
            actual = len(buf) - (pos + 8)
            if size != actual:
                buf[pos + 4:pos + 8] = struct.pack("<I", actual)
            buf[4:8] = struct.pack("<I", len(buf) - 8)
            return bytes(buf)
        pos += 8 + size + (size & 1)
    return data
