"""资产出参适配：在 multimodal.Asset 上补 status / version / updated_at（v1.3 契约），并给升级过的 url 加 ?v= 防缓存。"""
from __future__ import annotations

import asyncio
from typing import Any

from app import multimodal
from app.db import AssetRow, session_scope
from app.schemas import Asset

MAX_WAIT_S = 8.0


def _iso(d: Any) -> str:
    if not d:
        return ""
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def enrich(a: Asset | None) -> Asset | None:
    if a is None:
        return None
    version, updated = 1, ""
    try:
        with session_scope() as s:
            r = s.get(AssetRow, a.id)
            if r:
                version, updated = int(r.version or 1), _iso(r.updated_at or r.created_at)
    except Exception:  # noqa: BLE001 - 未落库的应急资产
        pass
    url = a.url.split("?v=")[0]
    if version > 1:
        url = f"{url}{'&' if '?' in url else '?'}v={version}"
    pending = False
    try:
        pending = bool(multimodal.is_pending(a.id))
    except Exception:  # noqa: BLE001
        pass
    return a.model_copy(update={"url": url, "version": version, "updated_at": updated or a.created_at,
                                "status": "pending" if pending else "ready"})


def enrich_all(items: list[Asset]) -> list[Asset]:
    return [x for x in (enrich(a) for a in items) if x is not None]


def get(asset_id: str) -> Asset | None:
    return enrich(multimodal.get_asset(asset_id))


async def wait(asset_id: str, seconds: float) -> Asset | None:
    """长轮询：等到占位升级完成（或超时，上限 MAX_WAIT_S）再返回当前记录。"""
    t = max(0.0, min(MAX_WAIT_S, seconds))
    if t and multimodal.is_pending(asset_id):
        await multimodal.wait_for_asset(asset_id, timeout=t)
    return get(asset_id)


async def watch(ids: set[str], emit: Any, *, stop: asyncio.Event, interval: float = 0.4) -> None:
    """SSE 流仍打开期间：被关注的占位资产一旦升级完成 → 在流内推送 asset（同 id、新 url、status=ready）。"""
    while not stop.is_set():
        await sweep(ids, emit)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def sweep(ids: set[str], emit: Any) -> None:
    for i in [x for x in ids if not multimodal.is_pending(x)]:
        ids.discard(i)
        if a := get(i):
            await emit("asset", a.model_dump())


def world_pending(world_id: str) -> set[str]:
    out = set()
    for i in multimodal.pending_ids():
        a = multimodal.get_asset(i)
        if a and a.world_id == world_id:
            out.add(i)
    return out
