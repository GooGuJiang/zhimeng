"""F6 生成式 UI 规格接口。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body

from app.config import get_settings
from app.graph.turn_graph import current_options
from app.routes.deps import world_or_404
from app.schemas import UIStreamRequest
from app.services import repo
from app.services.sse import sse_response
from app.ui.components import build_components

router = APIRouter(tags=["ui"])


@router.get("/worlds/{world_id}/ui")
async def ui(world_id: str, components: str | None = None, focus: str | None = None):
    w = world_or_404(world_id)
    types = [t.strip() for t in components.split(",") if t.strip()] if components else None
    comps = build_components(w, events=repo.list_events(world_id, limit=8), options=current_options(w),
                             types=types, focus=focus)
    return {"components": comps, "ai_generated": True}


@router.post("/worlds/{world_id}/ui/stream")
async def ui_stream(world_id: str, body: UIStreamRequest | None = Body(default=None)):
    w = world_or_404(world_id)
    focus = body.focus if body else None

    async def gen():
        yield "progress", {"stage": "ui", "message": "界面导演根据剧情布局组件…", "pct": 10, "percent": 10}
        comps = build_components(w, events=repo.list_events(world_id, limit=8), options=current_options(w), focus=focus)
        for i, c in enumerate(comps):
            yield "ui", {"components": [c]}
            if get_settings().stream_delay:
                await asyncio.sleep(get_settings().stream_delay * 5)
        yield "done", {"count": len(comps)}
    return sse_response(gen())
