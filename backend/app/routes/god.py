"""F7 上帝视角：NPC 状态与轨迹、事件注入（记忆留痕，影响后续叙事）、手动推进。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.graph.turn_graph import chapter_of, god_tick, world_lock
from app.memory import store
from app.routes.deps import world_or_404
from app.schemas import InjectRequest, WorldEvent
from app.services import guard, repo

router = APIRouter(tags=["god"])


@router.get("/worlds/{world_id}/god/npcs")
async def npcs(world_id: str):
    w = world_or_404(world_id)
    trajs = repo.list_trajectories(world_id)
    events = repo.list_events(world_id, limit=300)
    mems = store.list_memories(world_id, limit=2000)
    out = []
    for c in w.npcs():
        traj = [{"turn": t.turn, "location_id": t.location_id,
                 "location_name": (w.loc(t.location_id).name if w.loc(t.location_id) else None),
                 "action": t.action, "mood": t.mood, "timestamp": t.timestamp.isoformat()}
                for t in trajs if t.character_id == c.id]
        out.append({"character": c.model_dump(), "trajectory": traj,
                    "recent_events": [e.model_dump() for e in events if c.id in e.actor_ids][:5],
                    "memories": [m.content for m in mems if (m.refs or {}).get("character_id") == c.id][:8]})
    return out


@router.post("/worlds/{world_id}/god/inject", response_model=WorldEvent)
async def inject(world_id: str, body: InjectRequest):
    w = world_or_404(world_id)
    v = await guard.check_input(body.content, minor_mode=w.minor_mode, rating=w.rating, context="inject")
    if v.blocked:
        raise HTTPException(400, v.message or "注入内容未通过安全审核")
    valid = {c.id for c in w.npcs()}
    targets = [t for t in body.target_character_ids if t in valid]
    loc = body.location_id if w.loc(body.location_id) else None
    async with world_lock(world_id):
        nxt = w.state.turn + 1
        ev = repo.add_event(world_id, type="injected", summary=body.content.strip(), actor_ids=targets, location_id=loc,
                            turn=w.state.turn, chapter=chapter_of(nxt) if w.state.turn else 1, impact=body.impact,
                            in_world_time=w.state.time)
        where = f"（地点：{w.loc(loc).name}）" if loc else ""
        who = "、".join(w.char(t).name for t in targets if w.char(t))
        await store.add_memories(world_id, [{
            "content": f"【上帝视角插入事件】{body.content.strip()}{where}{'，涉及' + who if who else ''}",
            "kind": "injected", "turn": w.state.turn, "chapter": ev.chapter,
            "refs": {"event_id": ev.id, **({"character_id": targets[0]} if targets else {})}}])
    return ev


@router.post("/worlds/{world_id}/god/tick")
async def tick(world_id: str):
    world_or_404(world_id)
    events = await god_tick(world_id)
    return {"events": [e.model_dump() for e in events]}
