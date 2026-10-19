"""F5 multimodal — implementation behind the stable interface in /TEAM.md.

illustrate → 百炼万相文生图 (async task + poll), speak → Qwen-TTS. Both are cached by content hash in
``data/assets`` + table ``assets`` and fall back to an SVG placeholder / silent WAV (``source="fallback"``)
on any failure. Extra keyword-only params are optional additions; the TEAM.md signatures are unchanged.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.multimodal import assets as _a
from app.multimodal.voices import ALL_VOICES
from app.schemas import Asset

log = logging.getLogger("zhimeng.multimodal")
STATIC_PREFIX = _a.STATIC_PREFIX


def _emergency(world_id: str, kind: str, prompt: str, turn_id: str | None) -> Asset:
    """Last resort when even the local fallback path failed (e.g. DB/disk error): an unsaved Asset that
    points at a placeholder file if it can be written. Keeps the "never raise" contract."""
    from app.multimodal.fallback import placeholder_svg, silent_wav

    fname = f"{'img_fb' if kind == 'image' else 'tts_fb'}_emergency.{'svg' if kind == 'image' else 'wav'}"
    try:
        p = _a._assets_dir() / fname
        if not p.exists():
            p.write_bytes(placeholder_svg("织梦") if kind == "image" else silent_wav())
    except Exception:  # noqa: BLE001
        pass
    return Asset(id=f"ast_tmp_{uuid.uuid4().hex[:10]}", world_id=world_id, type=kind,  # type: ignore[arg-type]
                 url=_a._url(fname), turn_id=turn_id, prompt=prompt[:500], source="fallback")


async def illustrate(world_id: str, prompt: str, *, turn_id: str | None = None, style: str | None = None,
                     force: bool = False, minor_mode: bool = False, deadline: float | None = None) -> Asset:
    """Create (or reuse cached) illustration for a scene prompt. Never raises.

    ``deadline`` (seconds, optional): if the real image is not ready in time, return a placeholder Asset
    (``source="fallback"``) immediately; generation continues in the background and then upgrades the SAME
    row in place (same id, ``source="dashscope"``, new url). Poll ``get_asset(id)`` / ``list_assets`` or use
    ``wait_for_asset``; ``is_pending(id)`` tells whether an upgrade is still running."""
    full = f"{style}。{prompt}" if style else (prompt or "")
    try:
        return await _a.generate_illustration(world_id, full, turn_id=turn_id, force=force, minor_mode=minor_mode,
                                              deadline=deadline)
    except Exception as e:  # noqa: BLE001
        log.error("illustrate failed even in fallback: %s", type(e).__name__)
        return _emergency(world_id, "image", full, turn_id)


async def speak(world_id: str, text: str, *, voice: str | None = None, turn_id: str | None = None,
                force: bool = False, speaker: str | dict[str, Any] | None = None,
                deadline: float | None = None) -> Asset:
    """Create (or reuse cached) narration / NPC audio (wav). ``voice`` = a Qwen-TTS voice id, ``"narrator"``,
    or a character name (→ stable NPC voice); ``speaker`` = a Character dict (gender-aware casting).
    Fallback = silent WAV with ``source="fallback"`` (frontend may use Web Speech with ``asset.prompt``).
    ``deadline`` as in ``illustrate`` (placeholder now, same row upgraded later). Never raises."""
    if voice and voice not in ALL_VOICES and speaker is None:
        speaker, voice = voice, None
    try:
        a = await _a.generate_tts(world_id, text or "……", voice=voice, turn_id=turn_id,
                                  speaker=speaker or "narrator", force=force, allow_fallback=True, deadline=deadline)
        if a is not None:
            return a
    except Exception as e:  # noqa: BLE001
        log.error("speak failed even in fallback: %s", type(e).__name__)
    return _emergency(world_id, "audio", text or "", turn_id)


async def regenerate(asset_id: str, *, deadline: float | None = None) -> Asset | None:
    """Same type/prompt (and voice), bypass cache, new file. ``None`` if the asset id is unknown."""
    try:
        return await _a.regenerate_asset(asset_id, deadline=deadline)
    except Exception as e:  # noqa: BLE001
        log.error("regenerate failed: %s", type(e).__name__)
        return None


def list_assets(world_id: str) -> list[Asset]:
    return _a.list_assets(world_id)
