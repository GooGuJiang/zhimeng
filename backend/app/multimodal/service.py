"""STUB multimodal implementation (backend core): writes an SVG placeholder for images and a
short silent WAV for audio, cached by content hash in ``data/assets`` and recorded in the
``assets`` table. The multimodal engineer replaces internals with DashScope wanx / qwen-tts;
keep signatures stable (see /TEAM.md)."""
from __future__ import annotations

import hashlib
import html
import struct
import uuid

from sqlmodel import select

from app.config import get_settings
from app.db import AssetRow, session_scope
from app.schemas import Asset

STATIC_PREFIX = "/api/static/assets"


def _to_asset(r: AssetRow) -> Asset:
    return Asset(id=r.id, world_id=r.world_id, type=r.type, url=r.url, turn_id=r.turn_id,  # type: ignore[arg-type]
                 prompt=r.prompt, source=r.source, created_at=r.created_at.isoformat())


def _cached(world_id: str, key: str) -> Asset | None:
    with session_scope() as s:
        r = s.exec(select(AssetRow).where(AssetRow.world_id == world_id, AssetRow.cache_key == key)).first()
        return _to_asset(r) if r else None


def _save(world_id: str, type_: str, filename: str, data: bytes, prompt: str, key: str,
          turn_id: str | None, source: str = "fallback") -> Asset:
    (get_settings().assets_dir / filename).write_bytes(data)
    row = AssetRow(id=f"as_{uuid.uuid4().hex[:12]}", world_id=world_id, type=type_,
                   url=f"{STATIC_PREFIX}/{filename}", turn_id=turn_id, prompt=prompt, cache_key=key, source=source)
    with session_scope() as s:
        s.add(row)
    return _to_asset(row)


def _svg(prompt: str, seed: str) -> bytes:
    h = hashlib.md5(seed.encode()).hexdigest()
    c1, c2 = f"#{h[:6]}", f"#{h[6:12]}"
    text = html.escape(prompt[:40])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="576" viewBox="0 0 1024 576">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/>'
            f'<stop offset="1" stop-color="{c2}"/></linearGradient></defs><rect width="1024" height="576" fill="url(#g)"/>'
            f'<text x="512" y="288" font-size="32" text-anchor="middle" fill="#fff" font-family="sans-serif">{text}</text>'
            f'<text x="1004" y="556" font-size="18" text-anchor="end" fill="#fff" opacity="0.8">内容由AI生成</text></svg>').encode()


def _silent_wav(seconds: float = 0.5, rate: int = 16000) -> bytes:
    n = int(seconds * rate)
    data = b"\x00\x00" * n
    return b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(data)) + data


async def illustrate(world_id: str, prompt: str, *, turn_id: str | None = None,
                     style: str | None = None, force: bool = False) -> Asset:
    """Create (or reuse cached) illustration for a scene prompt."""
    key = "img:" + hashlib.sha1(f"{prompt}|{style}".encode()).hexdigest()
    if not force and (hit := _cached(world_id, key)):
        return hit
    name = f"{world_id}_{uuid.uuid4().hex[:8]}.svg"
    return _save(world_id, "image", name, _svg(prompt, name), prompt, key, turn_id)


async def speak(world_id: str, text: str, *, voice: str | None = None, turn_id: str | None = None,
                force: bool = False) -> Asset:
    """Create (or reuse cached) narration audio. Fallback audio is silent; frontend may use Web Speech
    with ``asset.prompt`` (the text) when ``source == 'fallback'``."""
    key = "tts:" + hashlib.sha1(f"{text}|{voice}".encode()).hexdigest()
    if not force and (hit := _cached(world_id, key)):
        return hit
    name = f"{world_id}_{uuid.uuid4().hex[:8]}.wav"
    return _save(world_id, "audio", name, _silent_wav(), text, key, turn_id)


async def regenerate(asset_id: str) -> Asset | None:
    with session_scope() as s:
        r = s.get(AssetRow, asset_id)
        if not r:
            return None
        row = _to_asset(r)
    if row.type == "image":
        return await illustrate(row.world_id, row.prompt, turn_id=row.turn_id, force=True)
    return await speak(row.world_id, row.prompt, turn_id=row.turn_id, force=True)


def list_assets(world_id: str) -> list[Asset]:
    with session_scope() as s:
        rows = s.exec(select(AssetRow).where(AssetRow.world_id == world_id).order_by(AssetRow.created_at)).all()
        return [_to_asset(r) for r in rows]
