"""F5 multimodal asset service: key-scene illustration (Wanx) + narration/NPC voice (Qwen-TTS).

Cost controls
- only key scenes trigger auto generation (opening, chapter boundary, injected / high-impact events)
- content-hash cache (type|model|voice|prompt) → same prompt never billed twice, across worlds
- n=1, prompt_extend=false, TTS text truncated to ``TTS_MAX_CHARS`` (first sentences of the narration)
- per-world budget (``ZM_MAX_IMAGES_PER_WORLD`` / ``ZM_MAX_TTS_PER_WORLD``) and a global concurrency limit
- provider moderation errors (DataInspectionFailed) are not retried; fallback is served instead
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from sqlmodel import select

from app.config import get_settings
from app.db import AssetRow, session_scope
from app.multimodal import dashscope_api as ds
from app.multimodal.fallback import fix_wav_header, placeholder_svg, silent_wav
from app.multimodal.voices import NARRATOR_VOICE, voice_for
from app.multimodal.voices import pools as voices_pools
from app.safety import keywords as kw
from app.safety.labels import ai_meta, png_with_ai_metadata
from app.schemas import Asset

log = logging.getLogger("zhimeng.multimodal")
STATIC_PREFIX = "/api/static/assets"  # mounted by app/main.py (TEAM.md)

MAX_IMAGES_PER_WORLD = int(os.getenv("ZM_MAX_IMAGES_PER_WORLD", "30"))
MAX_TTS_PER_WORLD = int(os.getenv("ZM_MAX_TTS_PER_WORLD", "60"))
TTS_MAX_CHARS = int(os.getenv("ZM_TTS_MAX_CHARS", "200"))
IMAGE_SIZE = os.getenv("ZM_IMAGE_SIZE", "1280*720")
IMAGES_ENABLED = os.getenv("ZM_IMAGES", "1").lower() not in {"0", "false", "no"}
TTS_ENABLED = os.getenv("ZM_TTS", "1").lower() not in {"0", "false", "no"}
STYLE = "国风插画，电影感构图，细腻光影，叙事场景插图，高清"
NEGATIVE = "文字，水印，签名，低画质，模糊，畸形手指，多余肢体，裸露，色情，血腥，恐怖内脏"

RETRY_AFTER = float(os.getenv("ZM_MM_RETRY_AFTER", "60"))  # seconds before a failed prompt hits the API again
_recent_fail: dict[str, float] = {}
_sem: asyncio.Semaphore | None = None
_inflight: dict[str, asyncio.Future] = {}
STATS: dict[str, int] = {"image_calls": 0, "tts_calls": 0, "cache_hits": 0, "fallbacks": 0, "tts_chars": 0}


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(int(os.getenv("ZM_MM_CONCURRENCY", "2")))
    return _sem


def _now_iso(dt) -> str:
    return dt.isoformat() if dt else ""


def to_asset(r: AssetRow) -> Asset:
    return Asset(id=r.id, world_id=r.world_id, type=r.type, url=r.url, turn_id=r.turn_id, prompt=r.prompt,
                 source=r.source, created_at=_now_iso(r.created_at))


def cache_key(kind: str, model: str, voice: str, prompt: str) -> str:
    return hashlib.sha256(f"{kind}|{model}|{voice}|{prompt}".encode()).hexdigest()


def _assets_dir() -> Path:
    d = get_settings().assets_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def _url(fname: str) -> str:
    return f"{STATIC_PREFIX}/{fname}"


def _count(world_id: str, kind: str) -> int:
    with session_scope() as s:
        rows = s.exec(select(AssetRow).where(AssetRow.world_id == world_id, AssetRow.type == kind,
                                             AssetRow.source == "dashscope")).all()
        return len(rows)


def _file_ok(r: AssetRow) -> bool:
    return (_assets_dir() / Path(r.url).name).exists()


def _find_cached(key: str, world_id: str, allow_fallback: bool) -> tuple[AssetRow | None, AssetRow | None]:
    """(row for this world, reusable real row from any world) for the cache key.

    Real (``dashscope``) rows are preferred. Fallback rows are only served from cache while remote
    generation is unavailable, so a placeholder is replaced by a real asset once a key works again.
    """
    with session_scope() as s:
        rows = s.exec(select(AssetRow).where(AssetRow.cache_key == key).order_by(AssetRow.created_at)).all()
    real = [r for r in rows if r.source == "dashscope" and _file_ok(r)]
    same = next((r for r in real if r.world_id == world_id), None)
    if same is None and allow_fallback:
        same = next((r for r in rows if r.world_id == world_id and r.source == "fallback" and _file_ok(r)), None)
    other = next(iter(real), None)
    return same, other


def _save(world_id: str, kind: str, url: str, prompt: str, key: str, source: str,
          turn_id: str | None) -> Asset:
    row = AssetRow(id=f"ast_{uuid.uuid4().hex[:12]}", world_id=world_id, type=kind, url=url, turn_id=turn_id,
                   prompt=prompt, cache_key=key, source=source)
    with session_scope() as s:
        s.add(row)
    return to_asset(row)


def _sanitize_prompt(text: str) -> str:
    """Strip hard-block / gore words before sending to the image model (avoids DataInspectionFailed)."""
    hits = kw.find(text, kw.HARD_BLOCK)
    hits.update({"m": kw.find(text, kw.RATING_HINTS).get("mature", [])})
    words = [w for ws in hits.values() for w in ws]
    out = text
    for w in words:
        out = re.sub(re.escape(w), "", out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip()


def build_scene_prompt(world: dict[str, Any] | None, narration: str = "", location: str | None = None,
                       minor_mode: bool = False) -> str:
    """Compose an illustration prompt from world style + current scene (≤500 chars for wanx2.x)."""
    w = world or {}
    parts = [STYLE]
    era = "，".join(x for x in (w.get("era"), w.get("genre"), w.get("tone")) if x)
    if era:
        parts.append(f"风格：{era}")
    if location:
        parts.append(f"地点：{location}")
    scene = re.sub(r"\s+", " ", narration or w.get("opening_scene") or w.get("premise") or "")[:260]
    if scene:
        parts.append(f"画面：{scene}")
    if minor_mode:
        parts.append("适合青少年，明亮温暖")
    return _sanitize_prompt("。".join(parts))[:500]


def tts_text(text: str, limit: int | None = None) -> str:
    """Trim narration to whole sentences within the TTS budget."""
    limit = limit or TTS_MAX_CHARS
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    m = max(cut.rfind(p) for p in "。！？!?…")
    return cut[: m + 1] if m >= limit // 3 else cut


async def _dedup(key: str, factory):
    """Coalesce concurrent identical requests into one provider call."""
    if key in _inflight:
        return await asyncio.shield(_inflight[key])
    fut = asyncio.get_running_loop().create_future()
    _inflight[key] = fut
    try:
        res = await factory()
        fut.set_result(res)
        return res
    except BaseException as e:
        fut.set_exception(e)
        fut.exception()  # mark retrieved
        raise
    finally:
        _inflight.pop(key, None)


def _update_row(row_id: str, url: str, source: str, turn_id: str | None) -> Asset | None:
    """Upgrade a cached fallback row in place (same id) once a real asset was generated (BUG-005)."""
    with session_scope() as s:
        r = s.get(AssetRow, row_id)
        if not r:
            return None
        r.url, r.source = url, source
        if turn_id and not r.turn_id:
            r.turn_id = turn_id
        s.add(r)
        s.flush()
        return to_asset(r)


def _persist(world_id: str, kind: str, url: str, prompt: str, key: str, source: str, turn_id: str | None,
             upgrade: AssetRow | None) -> Asset:
    if upgrade is not None:
        a = _update_row(upgrade.id, url, source, turn_id)
        if a:
            return a
    return _save(world_id, kind, url, prompt, key, source, turn_id)


def _cooling(key: str) -> bool:
    t = _recent_fail.get(key)
    return t is not None and time.monotonic() - t < RETRY_AFTER


def _remote_ok(world_id: str, kind: str) -> bool:
    s = get_settings()
    if not s.llm_enabled:  # no key or ZM_FORCE_FALLBACK=1 → zero remote calls
        return False
    if kind == "image":
        return IMAGES_ENABLED and _count(world_id, "image") < MAX_IMAGES_PER_WORLD
    return TTS_ENABLED and _count(world_id, "audio") < MAX_TTS_PER_WORLD


def _unique(prefix: str, key: str, ext: str, force: bool) -> str:
    return f"{prefix}_{key[:16]}{'_' + uuid.uuid4().hex[:6] if force else ''}.{ext}"


async def generate_illustration(world_id: str, prompt: str, turn_id: str | None = None,
                                force: bool = False, minor_mode: bool = False) -> Asset:
    """Return an image Asset (cached by prompt hash). Never raises for API failure: SVG placeholder fallback."""
    s = get_settings()
    prompt = _sanitize_prompt(prompt or "")[:500] or STYLE
    key = cache_key("image", s.image_model, IMAGE_SIZE, prompt)
    remote = _remote_ok(world_id, "image") and (force or not _cooling(key))
    upgrade: AssetRow | None = None  # cached fallback row to upgrade in place (BUG-005)
    if not force:
        same, other = _find_cached(key, world_id, allow_fallback=True)
        if same and (same.source != "fallback" or not remote):
            STATS["cache_hits"] += 1
            return to_asset(same)
        upgrade = same
        if other:  # same prompt already generated for another world: reuse the file, no new bill
            STATS["cache_hits"] += 1
            return _persist(world_id, "image", other.url, prompt, key, "dashscope", turn_id, upgrade)
    if remote:
        try:
            async def call() -> bytes:
                async with _semaphore():
                    STATS["image_calls"] += 1
                    neg = NEGATIVE + ("，暴力，惊悚" if minor_mode else "")
                    return await ds.text_to_image(prompt, neg, IMAGE_SIZE)
            data = await (call() if force else _dedup(key, call))
            data = png_with_ai_metadata(data, ai_meta(s.image_model, "image", prompt=prompt[:200]))
            fname = _unique("img", key, "png", force)
            (_assets_dir() / fname).write_bytes(data)
            _recent_fail.pop(key, None)
            return _persist(world_id, "image", _url(fname), prompt, key, "dashscope", turn_id, upgrade)
        except Exception as e:  # noqa: BLE001 - any failure → placeholder
            _recent_fail[key] = time.monotonic()
            log.warning("image generation failed, using placeholder: %s: %s", type(e).__name__, ds.redact(e))
    STATS["fallbacks"] += 1
    if upgrade is not None:  # retry failed → keep serving the existing placeholder row, no new row
        return to_asset(upgrade)
    fname = _unique("img_fb", key, "svg", force)
    path = _assets_dir() / fname
    if not path.exists():
        m = re.search(r"地点：([^。]+)", prompt)
        cap = re.search(r"画面：([^。]+(?:。[^。]+)?)", prompt)
        title = m.group(1) if m else "织梦"
        path.write_bytes(placeholder_svg(title, cap.group(1) if cap else prompt[:80]))
    return _save(world_id, "image", _url(fname), prompt, key, "fallback", turn_id)


def _supported_voice(v: str | None, speaker: str | dict[str, Any] | None) -> str:
    """Explicit voice if the configured model supports it, else cast from the speaker."""
    female, male = voices_pools()
    if v and (v in female or v in male or v == NARRATOR_VOICE):
        return v
    return voice_for(speaker)


async def generate_tts(world_id: str, text: str, voice: str | None = None, turn_id: str | None = None,
                       speaker: str | dict[str, Any] | None = None, force: bool = False,
                       allow_fallback: bool = True) -> Asset | None:
    """Return an audio Asset (wav). ``voice`` overrides speaker casting. Falls back to a silent WAV
    (``source="fallback"``) — or ``None`` when ``allow_fallback`` is False (e.g. auto key-scene audio → skip)."""
    s = get_settings()
    text = tts_text(text)
    if not text:
        return None
    v = _supported_voice(voice, speaker)
    model = ds.effective_tts_model()
    key = cache_key("audio", model, v, text)
    remote = _remote_ok(world_id, "audio") and (force or not _cooling(key))
    upgrade: AssetRow | None = None
    if not force:
        same, other = _find_cached(key, world_id, allow_fallback=allow_fallback)
        if same and (same.source != "fallback" or not remote):
            STATS["cache_hits"] += 1
            return to_asset(same)
        upgrade = same
        if other:
            STATS["cache_hits"] += 1
            return _persist(world_id, "audio", other.url, text, key, "dashscope", turn_id, upgrade)
    if remote:
        try:
            async def call() -> bytes:
                async with _semaphore():
                    STATS["tts_calls"] += 1
                    STATS["tts_chars"] += len(text)
                    return await ds.text_to_speech(text, v)
            data = await (call() if force else _dedup(key, call))
            if not data:
                raise ds.DashScopeError("EmptyAudio", "empty audio body")
            data = fix_wav_header(data)
            fname = _unique("tts", key, "wav", force)
            (_assets_dir() / fname).write_bytes(data)
            _recent_fail.pop(key, None)
            return _persist(world_id, "audio", _url(fname), text, key, "dashscope", turn_id, upgrade)
        except Exception as e:  # noqa: BLE001
            _recent_fail[key] = time.monotonic()
            log.warning("tts failed, using fallback: %s: %s", type(e).__name__, ds.redact(e))
    STATS["fallbacks"] += 1
    if upgrade is not None:
        return to_asset(upgrade)
    if not allow_fallback:
        return None
    fname = _unique("tts_fb", key, "wav", force)
    path = _assets_dir() / fname
    if not path.exists():
        path.write_bytes(silent_wav())
    return _save(world_id, "audio", _url(fname), text, key, "fallback", turn_id)


def get_asset(asset_id: str) -> Asset | None:
    with session_scope() as s:
        r = s.get(AssetRow, asset_id)
        return to_asset(r) if r else None


def list_assets(world_id: str, turn_id: str | None = None) -> list[Asset]:
    with session_scope() as s:
        q = select(AssetRow).where(AssetRow.world_id == world_id)
        if turn_id:
            q = q.where(AssetRow.turn_id == turn_id)
        return [to_asset(r) for r in s.exec(q.order_by(AssetRow.created_at)).all()]


def _voice_from_key(row: AssetRow) -> str | None:
    """Recover the voice of an audio asset from its cache key (no extra column needed)."""
    from app.multimodal.voices import ALL_VOICES
    model = ds.effective_tts_model()
    for v in ALL_VOICES:
        if cache_key("audio", model, v, row.prompt) == row.cache_key:
            return v
    return None


async def regenerate_asset(asset_id: str) -> Asset | None:
    """POST /api/assets/{id}/regenerate → new file (bypasses cache), same prompt/voice."""
    with session_scope() as s:
        r = s.get(AssetRow, asset_id)
    if not r:
        return None
    if r.type == "image":
        return await generate_illustration(r.world_id, r.prompt, r.turn_id, force=True)
    return await generate_tts(r.world_id, r.prompt, voice=_voice_from_key(r), turn_id=r.turn_id, force=True)


def is_key_scene(turn_index: int, events: list[dict[str, Any]] | None = None, chapter_size: int | None = None,
                 ending: bool = False) -> bool:
    """Opening (turn 0/1), first turn of each chapter, ending, or injected/high-impact events."""
    cs = chapter_size or get_settings().chapter_size
    if ending or turn_index <= 1:
        return True
    if cs and (turn_index - 1) % cs == 0:
        return True
    for e in events or []:
        if e.get("type") == "injected" or e.get("impact") == "high":
            return True
    return False


async def key_scene_assets(world: dict[str, Any], narration: str, turn_id: str | None = None,
                           location: str | None = None, with_audio: bool = True) -> list[Asset]:
    """Generate illustration + narrator audio concurrently for a key scene.
    Audio is skipped (not placeholder) when TTS is unavailable."""
    wid = world.get("id", "unknown")
    minor = bool(world.get("minor_mode"))
    prompt = build_scene_prompt(world, narration, location, minor)
    jobs = [generate_illustration(wid, prompt, turn_id, minor_mode=minor)]
    if with_audio:
        jobs.append(generate_tts(wid, narration, speaker="narrator", turn_id=turn_id, allow_fallback=False))
    res = await asyncio.gather(*jobs, return_exceptions=True)
    return [a for a in res if isinstance(a, Asset)]
