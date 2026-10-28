"""F2 叙事推进（SSE）+ F3 场外事件。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.graph.turn_graph import current_options, run_turn
from app.routes.deps import world_or_404
from app.schemas import SeenRequest, TurnRequest, WorldEvent
from app.services import repo
from app.services.sse import sse_response

router = APIRouter(tags=["play"])


@router.post("/worlds/{world_id}/turns")
async def play_turn(world_id: str, req: TurnRequest):
    world_or_404(world_id)
    return sse_response(run_turn(world_id, req))


@router.post("/worlds/{world_id}/turns/retry")
async def retry_turn(world_id: str):
    world_or_404(world_id)
    return sse_response(run_turn(world_id, None, retry=True))


@router.get("/worlds/{world_id}/turns")
async def list_turns(world_id: str, limit: int = Query(50, ge=1, le=1000)):
    world_or_404(world_id)
    return [t.model_dump() for t in repo.list_turns(world_id, limit=limit)]


@router.get("/worlds/{world_id}/options")
async def options(world_id: str):
    w = world_or_404(world_id)
    return {"options": [o.model_dump() for o in current_options(w)]}


@router.get("/worlds/{world_id}/events", response_model=list[WorldEvent])
async def events(world_id: str, type: str | None = None, limit: int = Query(50, ge=1, le=500)):  # noqa: A002
    world_or_404(world_id)
    return repo.list_events(world_id, type_=type, limit=limit)


@router.post("/worlds/{world_id}/events/seen")
async def events_seen(world_id: str, body: SeenRequest):
    world_or_404(world_id)
    want = set(body.ids)  # v1.4：只标记本世界的事件（防止按 id 改别人的世界）
    repo.mark_events([e.id for e in repo.list_events(world_id, limit=100_000) if e.id in want], seen=True)
    return {"ok": True}
