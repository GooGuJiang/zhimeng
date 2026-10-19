"""AI-generated content labelling (F9; 《人工智能生成合成内容标识办法》: explicit + implicit labels).

- explicit: ``ai_generated`` / ``ai_label`` fields on payloads (``label``), visible text on placeholders,
  "AI生成" watermark on generated images (multimodal sets ``watermark=true``)
- implicit: ``ai_meta`` metadata dict; ``png_with_ai_metadata`` embeds it as PNG iTXt chunks
"""
from __future__ import annotations

import json
import struct
import zlib
from datetime import datetime, timezone
from typing import Any

from app.schemas import AI_LABEL  # single source of truth ("内容由AI生成")

def show_visible_label() -> bool:
    """Visible AI badges/watermarks (user request: off by default; ``ZM_SHOW_AI_LABEL=1`` re-enables).

    Only the *visible* explicit labels follow this switch; payload fields (``ai_generated``/``ai_label``)
    and implicit metadata (``ai_meta``, PNG iTXt) are always kept.
    """
    import os

    return os.getenv("ZM_SHOW_AI_LABEL", "0").strip().lower() in {"1", "true", "yes", "on"}


SAFETY_LABEL = "本内容由AI生成，已经过内容安全审核，仅供娱乐与学习参考"
RATING_LABELS = {"all": "全年龄", "teen": "12+", "mature": "16+"}
GENERATOR = "织梦 Zhimeng AI Narrative Engine"


def ai_meta(model: str | None = None, kind: str = "text", **extra: Any) -> dict[str, Any]:
    """Implicit label metadata to embed in payloads / exported files."""
    meta = {"ai_generated": True, "ai_label": AI_LABEL, "generator": GENERATOR, "content_type": kind,
            "model": model, "labelled_at": datetime.now(timezone.utc).isoformat()}
    meta.update(extra)
    return meta


def label(payload: dict[str, Any]) -> dict[str, Any]:
    """Add the explicit AI label fields to a JSON payload (in place, returns it)."""
    payload["ai_generated"] = True
    payload["ai_label"] = AI_LABEL
    return payload


def rating_label(rating: str) -> str:
    return RATING_LABELS.get(rating, rating)


def svg_label_text() -> str:
    return AI_LABEL


def _itxt(keyword: str, text: str) -> bytes:
    data = keyword.encode("latin-1") + b"\x00\x00\x00\x00\x00" + text.encode("utf-8")
    return struct.pack(">I", len(data)) + b"iTXt" + data + struct.pack(">I", zlib.crc32(b"iTXt" + data) & 0xFFFFFFFF)


def png_with_ai_metadata(png: bytes, meta: dict[str, Any] | None = None) -> bytes:
    """Insert iTXt chunks (``AIGC`` JSON + ``Description``) right after IHDR. Non-PNG input is returned as is."""
    sig = b"\x89PNG\r\n\x1a\n"
    if not png.startswith(sig) or len(png) < 33 or png[12:16] != b"IHDR":
        return png
    ihdr_end = 8 + 4 + 4 + struct.unpack(">I", png[8:12])[0] + 4
    chunks = _itxt("AIGC", json.dumps(meta or ai_meta(kind="image"), ensure_ascii=False)) + _itxt("Description", AI_LABEL)
    return png[:ihdr_end] + chunks + png[ihdr_end:]
