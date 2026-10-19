"""F8 存档导出/导入（可跨会话继续游玩）与结局海报数据。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from app import multimodal
from app.db import AssetRow, SummaryRow, TrajectoryRow, TurnRow, session_scope
from app.memory import store
from app.routes.deps import world_or_404
from app.schemas import AI_LABEL, World
from app.services import guard, repo

router = APIRouter(tags=["save"])
THEMES = {"悬疑": ("#c9a86a", "#3b2f2f", "#14110f"), "仙侠": ("#7fb8a4", "#e8e2d0", "#0f1a17"),
          "科幻": ("#4dd0e1", "#b388ff", "#0a0f1f"), "奇幻": ("#e0b0ff", "#ffd479", "#1a1030"),
          "校园": ("#ff9eb5", "#8fd3ff", "#fff7f0"), "教育": ("#c0392b", "#d4ac6e", "#f7f1e3")}


@router.get("/worlds/{world_id}/export")
async def export(world_id: str):
    w = world_or_404(world_id)
    mems = store.list_memories(world_id, limit=100_000)
    return {"format": "zhimeng-save", "version": 1, "exported_at": datetime.now(timezone.utc).isoformat(),
            "world": w.model_dump(mode="json"),
            "turns": [t.model_dump() for t in repo.list_turns(world_id, limit=100_000)],
            "turn_snapshots": {r.id: r.state_before for r in _turn_rows(world_id)},
            "events": [e.model_dump() for e in repo.list_events(world_id, limit=100_000)],
            "memories": [{**store.to_item(m).model_dump(), "refs": m.refs} for m in reversed(mems)],
            "summaries": [{"chapter": s.chapter, "from_turn": s.from_turn, "to_turn": s.to_turn, "summary": s.summary}
                          for s in repo.list_summaries(world_id)],
            "trajectories": [{"character_id": t.character_id, "turn": t.turn, "location_id": t.location_id,
                              "action": t.action, "mood": t.mood, "timestamp": t.timestamp.isoformat()}
                             for t in repo.list_trajectories(world_id)],
            "assets": [a.model_dump() for a in multimodal.list_assets(world_id)],
            "ai_generated": True, "ai_label": AI_LABEL}


def _turn_rows(world_id: str) -> list[TurnRow]:
    from sqlmodel import select
    with session_scope() as s:
        return list(s.exec(select(TurnRow).where(TurnRow.world_id == world_id)).all())


def _dt(v: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


@router.post("/worlds/import", response_model=World)
async def import_save(save: dict[str, Any] = Body(...)):
    if save.get("format") != "zhimeng-save":
        raise HTTPException(400, "不是有效的织梦存档（format 应为 zhimeng-save）")
    try:
        world = World.model_validate(save["world"])
    except (KeyError, ValidationError) as e:
        raise HTTPException(400, f"存档中的世界数据无效：{e}") from e
    # 导入的文本同样需过安全审核（存档可被手工编辑）
    v = await guard.check_input(f"{world.title}\n{world.setting}\n{world.opening_scene}", minor_mode=world.minor_mode,
                                rating=world.rating, context="source_text")
    if v.blocked:
        raise HTTPException(400, v.message or "存档内容未通过安全审核")
    old_id, wid = world.id, repo.new_id("w")
    world.id, world.created_at = wid, ""
    repo.save_world(world)
    ev_map: dict[str, str] = {}
    for e in sorted(save.get("events") or [], key=lambda e: str(e.get("timestamp", ""))):
        ne = repo.add_event(wid, type=e.get("type", "world"), summary=e.get("summary", ""), actor_ids=e.get("actor_ids") or [],
                            location_id=e.get("location_id"), turn=int(e.get("turn", 0)), chapter=int(e.get("chapter", 1)),
                            impact=e.get("impact", "low"), in_world_time=e.get("in_world_time", ""))
        ev_map[e.get("id", "")] = ne.id
        if e.get("seen"):
            repo.mark_events([ne.id], seen=True)
    snaps = save.get("turn_snapshots") or {}
    with session_scope() as s:
        for t in save.get("turns") or []:
            snap = dict(snaps.get(t.get("id"), {}) or {})
            if snap.get("world"):
                snap["world"] = {**snap["world"], "id": wid}
            s.add(TurnRow(id=repo.new_id("t"), world_id=wid, index=int(t["index"]), chapter=int(t.get("chapter", 1)),
                          action=t.get("action", ""), narration=t.get("narration", ""), options=t.get("options") or [],
                          facts=t.get("facts") or [], event_ids=[ev_map[e["id"]] for e in t.get("events") or [] if e.get("id") in ev_map],
                          key_scene=bool(t.get("key_scene")), source=str(t.get("source") or "llm"), state_before=snap,
                          created_at=_dt(t.get("created_at"))))
        for sm in save.get("summaries") or []:
            s.add(SummaryRow(id=repo.new_id("sm"), world_id=wid, chapter=int(sm["chapter"]), from_turn=int(sm["from_turn"]),
                             to_turn=int(sm["to_turn"]), summary=sm.get("summary", "")))
        for tr in save.get("trajectories") or []:
            s.add(TrajectoryRow(id=repo.new_id("tr"), world_id=wid, character_id=tr["character_id"], turn=int(tr.get("turn", 0)),
                                location_id=tr.get("location_id"), action=tr.get("action", ""), mood=tr.get("mood", ""),
                                timestamp=_dt(tr.get("timestamp"))))
        for a in save.get("assets") or []:
            if a.get("url") and a.get("type") in ("image", "audio"):
                s.add(AssetRow(id=repo.new_id("as"), world_id=wid, type=a["type"], url=a["url"], turn_id=None,
                               prompt=a.get("prompt", ""), cache_key=f"import:{old_id}:{a.get('id')}",
                               source=a.get("source", "fallback")))
    await store.add_memories(wid, [{"content": m.get("content", ""), "kind": m.get("kind", "fact"), "turn": int(m.get("turn", 0)),
                                    "chapter": int(m.get("chapter", 1)), "refs": m.get("refs") or {}}
                                   for m in save.get("memories") or []])
    return world


@router.get("/worlds/{world_id}/poster")
async def poster(world_id: str):
    w = world_or_404(world_id)
    sums = repo.list_summaries(world_id)
    turns = repo.list_turns(world_id, limit=100_000)
    images = [a for a in multimodal.list_assets(world_id) if a.type == "image"]
    key = next((k for k in THEMES if k in (w.genre or "") or (k == "教育" and w.mode == "education")), None)
    primary, secondary, bg = THEMES.get(key or "", ("#d4a373", "#6b705c", "#1b1b1b"))
    summary = sums[-1].summary if sums else (turns[-1].narration[:120] if turns else w.setting[:120])
    return {"title": w.title, "subtitle": "·".join(x for x in (w.genre, w.era) if x), "tagline": w.premise[:60],
            "summary": summary, "ending": w.state.flags.get("ending"),
            "characters": [{"name": c.name, "role": c.role, "emoji": c.avatar_emoji or "👤"} for c in w.npcs()][:6],
            "stats": {"turns": len(turns), "chapters": w.state.chapter, "events": len(repo.list_events(world_id, limit=100_000))},
            "image_url": images[-1].url if images else None,
            "theme": {"primary": primary, "secondary": secondary, "background": bg},
            "qr_text": f"织梦·{w.title}｜我在《{w.title}》里走过了 {len(turns)} 个回合", "ai_generated": True,
            "ai_label": AI_LABEL, "safety_label": guard.safety_label(), "rating": w.rating}
