"""Repository helpers: World JSON <-> SQLite rows, events, turns, trajectories, summaries."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import col, delete, select

from app.db import (BranchRow, CharacterRow, EventRow, SummaryRow, TrajectoryRow, TurnRow, WorldRow,
                    session_scope, utcnow)
from app.schemas import Option, Turn, World, WorldEvent, WorldSummary


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def iso(d: datetime) -> str:
    return d.isoformat()


# ---------------------------------------------------------------- v1.5 剧情线标记
def current_branch(world_id: str) -> str:
    """世界当前所在的剧情线（以已保存的世界为准；旧数据 = main）。"""
    with session_scope() as s:
        row = s.get(WorldRow, world_id)
        return str(((row.data or {}).get("branch_id") if row else None) or "main")


def branch_tag(world_id: str, turn: int, branch_id: str | None = None) -> str:
    """新写入的事件/轨迹/摘要/记忆属于哪条剧情线：开局（turn<=0）一律 main（所有路径共享），否则为给定线或当前线。"""
    if int(turn or 0) <= 0:
        return "main"
    return branch_id or current_branch(world_id)


# ---------------------------------------------------------------- worlds
def _owner_for_new(world: World) -> str:
    from app.auth.context import DEMO_ID, current_owner_id

    return current_owner_id() or world.owner_id or DEMO_ID


def save_world(world: World) -> World:
    """新建行：owner_id = 当前请求身份（无请求上下文 → world.owner_id / demo）；已有行：归属与来源不变。"""
    now = iso(utcnow())
    world.updated_at = now
    world.created_at = world.created_at or now
    with session_scope() as s:
        row = s.get(WorldRow, world.id)
        if row is None:
            world.owner_id = _owner_for_new(world)
            row = WorldRow(id=world.id, title=world.title, data={}, owner_id=world.owner_id, origin=world.origin)
        else:
            world.owner_id = row.owner_id or world.owner_id
            world.origin = (row.origin or "generated")  # type: ignore[assignment]
        data = world.model_dump(mode="json")
        row.title, row.genre, row.tone, row.mode, row.status = world.title, world.genre, world.tone, world.mode, world.status
        row.data = data
        row.updated_at = utcnow()
        s.add(row)
        s.exec(delete(CharacterRow).where(CharacterRow.world_id == world.id))  # type: ignore[call-overload]
        for c in world.characters:
            s.add(CharacterRow(id=c.id, world_id=world.id, name=c.name, persona=c.persona, goals=c.goals,
                               relations=[r.model_dump() for r in c.relations], location_id=c.location_id,
                               mood=c.mood, status=c.status))
    return world


def load_world(world_id: str) -> World | None:
    with session_scope() as s:
        row = s.get(WorldRow, world_id)
        if not row:
            return None
        w = World.model_validate(row.data)
        if w.gen_request is None and w.state.flags.get("gen_request"):  # 旧存档：从 flags 回填正式字段
            w.gen_request = w.state.flags["gen_request"]
        w.owner_id = row.owner_id or ""
        w.origin = (row.origin or "generated")  # type: ignore[assignment]
        # v1.4：归属用户的偏好开启了未成年人模式 → 读取时收紧（回合/生成审核都用收紧后的值；下次保存写回）
        if row.owner_id:
            from app.auth.prefs import effective
            from app.db import UserRow
            u = s.get(UserRow, row.owner_id)
            if u and (u.preferences or {}).get("minor_mode"):
                w.minor_mode, w.rating = effective(w.minor_mode, w.rating, u.preferences)  # type: ignore[assignment]
        return w


def world_owner(world_id: str) -> str | None:
    with session_scope() as s:
        row = s.get(WorldRow, world_id)
        return (row.owner_id or "") if row else None


def list_worlds(owner_id: str | None = None) -> list[WorldSummary]:
    """owner_id=None → 全部（仅内部使用，如启动时恢复补全）；接口层总是传当前用户。"""
    with session_scope() as s:
        q = select(WorldRow)
        if owner_id is not None:
            q = q.where(WorldRow.owner_id == owner_id)
        rows = s.exec(q.order_by(col(WorldRow.updated_at).desc())).all()
        return [WorldSummary(id=r.id, title=r.title, genre=r.genre, tone=r.tone, mode=r.mode,  # type: ignore[arg-type]
                             turn=(r.data or {}).get("state", {}).get("turn", 0), status=r.status,
                             created_at=iso(r.created_at), updated_at=iso(r.updated_at),
                             owner_id=r.owner_id or "") for r in rows]


def delete_world(world_id: str) -> bool:
    from app.memory import store

    with session_scope() as s:
        row = s.get(WorldRow, world_id)
        if not row:
            return False
        s.delete(row)
        for m in (CharacterRow, EventRow, TurnRow, TrajectoryRow, SummaryRow, BranchRow):
            s.exec(delete(m).where(m.world_id == world_id))  # type: ignore[call-overload]
    store.delete_world(world_id)
    return True


# ---------------------------------------------------------------- events
def event_out(r: EventRow) -> WorldEvent:
    return WorldEvent(id=r.id, world_id=r.world_id, type=r.type, summary=r.summary, actor_ids=r.actor_ids,
                      location_id=r.location_id, turn=r.turn, chapter=r.chapter, impact=r.impact,
                      timestamp=iso(r.timestamp), in_world_time=r.in_world_time, seen=r.seen)


def add_event(world_id: str, **kw: Any) -> WorldEvent:
    kw["branch_id"] = branch_tag(world_id, kw.get("turn", 0), kw.get("branch_id"))
    row = EventRow(id=kw.pop("id", None) or new_id("ev"), world_id=world_id, **kw)
    with session_scope() as s:
        s.add(row)
    return event_out(row)


def list_events(world_id: str, type_: str | None = None, limit: int = 50,
                min_turn: int | None = None) -> list[WorldEvent]:
    with session_scope() as s:
        q = select(EventRow).where(EventRow.world_id == world_id, EventRow.active == True)  # noqa: E712
        if type_:
            q = q.where(EventRow.type == type_)
        if min_turn is not None:
            q = q.where(EventRow.turn >= min_turn)
        rows = s.exec(q.order_by(col(EventRow.timestamp).desc()).limit(limit)).all()
        return [event_out(r) for r in rows]


def pending_injections(world_id: str) -> list[EventRow]:
    with session_scope() as s:
        return list(s.exec(select(EventRow).where(EventRow.world_id == world_id, EventRow.type == "injected",
                                                  EventRow.consumed == False, EventRow.active == True)).all())  # noqa: E712


def mark_events(ids: list[str], *, seen: bool | None = None, consumed: bool | None = None) -> None:
    if not ids:
        return
    with session_scope() as s:
        for r in s.exec(select(EventRow).where(col(EventRow.id).in_(ids))):
            if seen is not None:
                r.seen = seen
            if consumed is not None:
                r.consumed = consumed
            s.add(r)


# ---------------------------------------------------------------- turns
def turn_option_id(r: TurnRow) -> str | None:
    return r.option_id or (r.state_before or {}).get("option_id") or None


def turn_out(r: TurnRow, events: list[WorldEvent] | None = None) -> Turn:
    return Turn(id=r.id, world_id=r.world_id, index=r.index, chapter=r.chapter, action=r.action,
                narration=r.narration, options=[Option(**o) for o in r.options], events=events or [],
                facts=r.facts, asset_ids=r.asset_ids, key_scene=r.key_scene,
                source="fallback" if r.source == "fallback" else "llm", created_at=iso(r.created_at),
                parent_turn_id=r.parent_turn_id, branch_id=r.branch_id or "main", option_id=turn_option_id(r))


def list_turns(world_id: str, limit: int = 50) -> list[Turn]:
    """当前路径（开局 → 当前节点）上的回合，升序。"""
    with session_scope() as s:
        rows = list(s.exec(select(TurnRow).where(TurnRow.world_id == world_id, TurnRow.active == True)  # noqa: E712
                           .order_by(col(TurnRow.index).desc()).limit(limit)).all())
        evs = {e.id: event_out(e) for e in s.exec(select(EventRow).where(EventRow.world_id == world_id))}
    rows.reverse()
    return [turn_out(r, [evs[i] for i in r.event_ids if i in evs]) for r in rows]


def get_turn_row(world_id: str, *, index: int | None = None, client_turn_id: str | None = None,
                 turn_id: str | None = None) -> TurnRow | None:
    with session_scope() as s:
        q = select(TurnRow).where(TurnRow.world_id == world_id)
        if index is not None:  # 按序号查只看当前路径（各支线有相同序号）
            q = q.where(TurnRow.index == index, TurnRow.active == True)  # noqa: E712
        if client_turn_id is not None:
            q = q.where(TurnRow.client_turn_id == client_turn_id)
        if turn_id is not None:
            q = q.where(TurnRow.id == turn_id)
        return s.exec(q).first()


def last_turn_row(world_id: str) -> TurnRow | None:
    with session_scope() as s:
        return s.exec(select(TurnRow).where(TurnRow.world_id == world_id, TurnRow.active == True)  # noqa: E712
                      .order_by(col(TurnRow.index).desc())).first()


def rollback_from_turn(world_id: str, turn: int) -> None:
    """Delete everything produced at/after ``turn`` (turn rows, events, trajectories, summaries, memories).
    v1.5：只删当前路径上的（其它支线的同序号内容不受影响）。"""
    from app.memory import store

    on = True
    with session_scope() as s:
        s.exec(delete(TurnRow).where(TurnRow.world_id == world_id, TurnRow.index >= turn, TurnRow.active == on))  # type: ignore[call-overload]
        # 上帝视角注入（injected）与手动推进（origin=tick）是独立于回合的干预，重试时保留
        s.exec(delete(EventRow).where(EventRow.world_id == world_id, EventRow.turn >= turn,  # type: ignore[call-overload]
                                      EventRow.type != "injected", EventRow.origin != "tick", EventRow.active == on))
        s.exec(delete(TrajectoryRow).where(TrajectoryRow.world_id == world_id, TrajectoryRow.turn >= turn,  # type: ignore[call-overload]
                                           TrajectoryRow.origin != "tick", TrajectoryRow.active == on))
        s.exec(delete(SummaryRow).where(SummaryRow.world_id == world_id, SummaryRow.to_turn >= turn,  # type: ignore[call-overload]
                                        SummaryRow.active == on))
    store.delete_from_turn(world_id, turn)


# ---------------------------------------------------------------- trajectories / summaries
def add_trajectory(world_id: str, character_id: str, turn: int, location_id: str | None, action: str, mood: str,
                   origin: str = "turn", branch_id: str | None = None) -> None:
    br = branch_tag(world_id, turn, branch_id)
    with session_scope() as s:
        s.add(TrajectoryRow(id=new_id("tr"), world_id=world_id, character_id=character_id, turn=turn,
                            location_id=location_id, action=action, mood=mood, origin=origin, branch_id=br))


def tick_events_since(world_id: str, turn: int) -> list[EventRow]:
    """回合 ``turn`` 之后（含）上帝视角手动推进产生、尚未被回合吸收的事件（时间正序）。"""
    with session_scope() as s:
        return list(s.exec(select(EventRow).where(EventRow.world_id == world_id, EventRow.origin == "tick",
                                                  EventRow.turn >= turn, EventRow.active == True)  # noqa: E712
                           .order_by(EventRow.timestamp)).all())


def list_trajectories(world_id: str, character_id: str | None = None) -> list[TrajectoryRow]:
    with session_scope() as s:
        q = select(TrajectoryRow).where(TrajectoryRow.world_id == world_id, TrajectoryRow.active == True)  # noqa: E712
        if character_id:
            q = q.where(TrajectoryRow.character_id == character_id)
        return list(s.exec(q.order_by(TrajectoryRow.turn, TrajectoryRow.timestamp)).all())


def add_summary(world_id: str, chapter: int, from_turn: int, to_turn: int, summary: str,
                branch_id: str | None = None) -> None:
    br = branch_tag(world_id, to_turn, branch_id)
    with session_scope() as s:
        s.add(SummaryRow(id=new_id("sm"), world_id=world_id, chapter=chapter, from_turn=from_turn,
                         to_turn=to_turn, summary=summary, branch_id=br))


def list_summaries(world_id: str) -> list[SummaryRow]:
    with session_scope() as s:
        return list(s.exec(select(SummaryRow).where(SummaryRow.world_id == world_id, SummaryRow.active == True)  # noqa: E712
                           .order_by(SummaryRow.chapter)).all())
