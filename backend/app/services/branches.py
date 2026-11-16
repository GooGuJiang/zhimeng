"""v1.5 剧情树：回合构成一棵树（parent_turn_id / branch_id），「当前路径」= 开局 → 当前节点。

- 剧情线（branch）：main 隐式存在；从一个已有后续剧情的节点再走一步 → 新开一条线（BranchRow，记录分叉点）。
- 当前路径上的数据（回合/事件/轨迹/摘要/记忆）active=1，其余 active=0；只在「回到某个节点」时整体重算一次，
  所有列表/检索只看 active=1 → 其它支线的后续剧情和记忆不会带入当前路径。
- 回到节点 = 世界的剧情状态恢复为该节点回合结束时的快照（TurnRow.state_after；旧数据用子回合的 state_before 推出）。
所有面向玩家的文字（剧情线名称、提示、错误）都是普通中文。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, case, false, or_, update
from sqlmodel import col, func, select

from app.db import BranchRow, EventRow, MemoryRow, SummaryRow, TrajectoryRow, TurnRow, session_scope
from app.schemas import Option, Turn, World

OPENING = "opening"
MAIN = "main"
NOT_FOUND = "没有找到这段剧情"


class BranchError(Exception):
    """用户可见的分支操作错误（message 为中文提示）。"""


# ---------------------------------------------------------------- 基础查询
def get_row(world_id: str, turn_id: str) -> TurnRow | None:
    with session_scope() as s:
        r = s.get(TurnRow, turn_id)
        return r if r and r.world_id == world_id else None


def head_row(world: World) -> TurnRow | None:
    """当前所在节点（None = 开局）。旧存档没有 head_turn_id：turn>0 时取当前路径的最后一回合。"""
    if world.head_turn_id:
        r = get_row(world.id, world.head_turn_id)
        if r:
            return r
    if world.state.turn > 0:
        from app.services import repo
        return repo.last_turn_row(world.id)
    return None


def all_rows(world_id: str) -> list[TurnRow]:
    with session_scope() as s:
        return list(s.exec(select(TurnRow).where(TurnRow.world_id == world_id)
                           .order_by(TurnRow.index, TurnRow.created_at)).all())


def branch_rows(world_id: str) -> list[BranchRow]:
    with session_scope() as s:
        return list(s.exec(select(BranchRow).where(BranchRow.world_id == world_id).order_by(BranchRow.seq)).all())


def has_after(world_id: str, branch_id: str, index: int) -> bool:
    with session_scope() as s:
        return s.exec(select(TurnRow.id).where(TurnRow.world_id == world_id, TurnRow.branch_id == branch_id,
                                               TurnRow.index > index)).first() is not None


def has_children(world_id: str, turn_id: str | None) -> bool:
    with session_scope() as s:
        q = select(TurnRow.id).where(TurnRow.world_id == world_id)
        q = q.where(TurnRow.parent_turn_id == turn_id) if turn_id else q.where(col(TurnRow.parent_turn_id).is_(None))
        return s.exec(q).first() is not None


# ---------------------------------------------------------------- 剧情线
def plan_next(world: World) -> dict[str, Any]:
    """下一回合落在哪条线：当前节点是所在线的线尾 → 沿用；否则新开一条（真正创建在回合提交时）。"""
    head = head_row(world)
    hb, hi = (head.branch_id or MAIN, head.index) if head else (MAIN, 0)
    parent = head.id if head else None
    if not has_after(world.id, hb, hi):
        return {"branch_id": hb, "parent_turn_id": parent, "fork": None}
    bid = f"b_{uuid.uuid4().hex[:8]}"
    return {"branch_id": bid, "parent_turn_id": parent,
            "fork": {"id": bid, "parent_branch_id": hb, "fork_turn_id": parent, "fork_index": hi}}


def create_branch(world_id: str, fork: dict[str, Any]) -> None:
    with session_scope() as s:
        seq = (s.exec(select(func.max(BranchRow.seq)).where(BranchRow.world_id == world_id)).one() or 0) + 1
        s.add(BranchRow(id=fork["id"], world_id=world_id, parent_branch_id=fork["parent_branch_id"],
                        fork_turn_id=fork["fork_turn_id"], fork_index=int(fork["fork_index"]), seq=seq))


def drop_branch(world_id: str, branch_id: str) -> None:
    with session_scope() as s:
        r = s.get(BranchRow, (branch_id, world_id))
        if r:
            s.delete(r)


def label_of(world_id: str, branch_id: str) -> str:
    if branch_id == MAIN:
        return "主线"
    with session_scope() as s:
        r = s.get(BranchRow, (branch_id, world_id))
        return f"支线{r.seq}" if r else "支线"


def lineage(world_id: str, branch_id: str, cap: int) -> list[tuple[str, int]]:
    """当前路径由哪些 (剧情线, 截止回合) 段组成：本线截至 cap，父线截至分叉点……直到主线。"""
    brs = {b.id: b for b in branch_rows(world_id)}
    segs: list[tuple[str, int]] = []
    b, c, seen = branch_id or MAIN, cap, set()
    while True:
        segs.append((b, c))
        if b == MAIN or b in seen or b not in brs:
            break
        seen.add(b)
        b, c = brs[b].parent_branch_id or MAIN, brs[b].fork_index
    if segs[-1][0] != MAIN:  # 剧情线记录缺失：退回主线开局（开局数据总在主线）
        segs.append((MAIN, 0))
    return segs


_TURN_COL = {TurnRow: TurnRow.index, EventRow: EventRow.turn, TrajectoryRow: TrajectoryRow.turn,
             SummaryRow: SummaryRow.to_turn, MemoryRow: MemoryRow.turn}


def recompute_active(world_id: str, segs: list[tuple[str, int]]) -> None:
    """按当前路径重算所有数据的 active 标记，并让当前路径上尚未被本路径吸收的上帝视角注入重新生效。"""
    with session_scope() as s:
        for model, turn_col in _TURN_COL.items():
            cond = or_(*[and_(model.branch_id == b, turn_col <= c) for b, c in segs]) if segs else false()
            s.exec(update(model).where(model.world_id == world_id)  # type: ignore[call-overload]
                   .values(active=case((cond, True), else_=False)))
    with session_scope() as s:
        consumed: set[str] = set()
        for r in s.exec(select(TurnRow).where(TurnRow.world_id == world_id, TurnRow.active == True)):  # noqa: E712
            consumed |= set((r.state_before or {}).get("consumed") or [])
        for e in s.exec(select(EventRow).where(EventRow.world_id == world_id, EventRow.type == "injected",
                                               EventRow.active == True)):  # noqa: E712
            want = e.id in consumed
            if e.consumed != want:
                e.consumed = want
                s.add(e)


# ---------------------------------------------------------------- 回到某个节点
def _snapshot_after(world: World, row: TurnRow | None) -> dict[str, Any] | None:
    """节点回合结束时的世界快照：state_after → 任一子回合的 state_before → （当前节点）当前世界 → 本回合 state_before。"""
    with session_scope() as s:
        if row is None:  # 开局：任一根回合的回合前快照
            r = s.exec(select(TurnRow).where(TurnRow.world_id == world.id, col(TurnRow.parent_turn_id).is_(None))
                       .order_by(TurnRow.created_at)).first()
            return ((r.state_before or {}).get("world") if r else None) or None
        if row.state_after:
            return row.state_after
        child = s.exec(select(TurnRow).where(TurnRow.world_id == world.id, TurnRow.parent_turn_id == row.id)
                       .order_by(TurnRow.created_at)).first()
        if child and (child.state_before or {}).get("world"):
            return child.state_before["world"]
    return None


def restore(world: World, snap: dict[str, Any]) -> World:
    """把世界的剧情状态换成快照里的（时间/地点/属性/物品/知识卡/角色动态），设定类字段保持当前值。"""
    old = World.model_validate(snap)
    w = world.model_copy(deep=True)
    flags = {k: v for k, v in w.state.flags.items() if k != "ending"}
    flags.update(old.state.flags)
    w.state = old.state.model_copy(deep=True)
    w.state.flags = flags
    w.items = [i.model_copy() for i in old.items]
    if old.knowledge_cards or w.mode != "education":
        w.knowledge_cards = [k.model_copy() for k in old.knowledge_cards]
    for c in w.characters:
        oc = old.char(c.id)
        if oc:
            c.location_id, c.mood, c.status = oc.location_id, oc.mood, oc.status
            c.relations = [r.model_copy() for r in oc.relations]
    if old.status == "ended" or flags.get("ending"):
        w.status = "ended"
    elif w.status == "ended":
        w.status = "active"
    return w


def checkout(world: World, target_turn_id: str | None) -> World:
    """回到某个节点（None/"opening" = 开局）。调用方持有 world_lock。不生成内容、不调用模型。"""
    from app.services import repo
    if target_turn_id == OPENING:
        target_turn_id = None
    row = get_row(world.id, target_turn_id) if target_turn_id else None
    if target_turn_id and row is None:
        raise BranchError(NOT_FOUND)
    cur = head_row(world)
    if cur is not None:  # 离开前把当前世界（含上帝视角手动推进带来的变化）记到当前节点，切回来时原样恢复
        with session_scope() as s:
            r = s.get(TurnRow, cur.id)
            if r:
                r.state_after = world.model_dump(mode="json")
                s.add(r)
    same = (cur.id if cur else None) == (row.id if row else None)
    w = world
    if not same:
        snap = _snapshot_after(world, row)
        if snap:
            w = restore(world, snap)
        elif row is not None:  # 实在没有快照：至少把回合序号对齐
            w = world.model_copy(deep=True)
            w.state.turn, w.state.chapter = row.index, row.chapter
    w.head_turn_id = row.id if row else None
    w.branch_id = (row.branch_id or MAIN) if row else MAIN
    if row is None:
        w.state.turn = 0
    repo.save_world(w)
    recompute_active(world.id, lineage(world.id, w.branch_id, row.index if row else 0))
    return repo.load_world(world.id) or w


# ---------------------------------------------------------------- 视图
def _clip(text: str, n: int = 60) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[:n - 1] + "…"


def _choice_of(row: TurnRow, opts: list[dict[str, Any]]) -> dict[str, Any] | None:
    from app.services.repo import turn_option_id
    oid = turn_option_id(row)
    o = next((x for x in opts if oid and x.get("id") == oid), None)
    if o is None and row.action:
        o = next((x for x in opts if x.get("text") == row.action.strip()), None)
    return o


def _choices(world: World, opts: list[Any], kids: list[TurnRow]) -> list[dict[str, Any]]:
    from app.agents import fallback
    filled = fallback.fill_hints(world, [o if isinstance(o, dict) else o.model_dump() for o in opts])
    out = []
    for o in filled:
        took = [k for k in kids if (_choice_of(k, [o]) is not None)]
        took.sort(key=lambda k: (not k.active, k.created_at))
        out.append({**o, "taken_turn_id": took[0].id if took else None})
    return out


def taken_map(world: World, head: TurnRow | None, opts: list[Option]) -> dict[str, str]:
    kids = [r for r in all_rows(world.id) if r.parent_turn_id == (head.id if head else None)]
    return {c["id"]: c["taken_turn_id"] for c in _choices(world, opts, kids) if c["taken_turn_id"]}


def tree(world: World) -> dict[str, Any]:
    rows = all_rows(world.id)
    head = head_row(world)
    head_id = head.id if head else None
    kids: dict[str | None, list[TurnRow]] = {}
    for r in rows:
        kids.setdefault(r.parent_turn_id, []).append(r)
    by_id = {r.id: r for r in rows}
    nodes: list[dict[str, Any]] = []
    opening_choices = _choices(world, world.opening_options, kids.get(None, []))
    opening = {"preview": _clip(world.opening_scene) or "故事从这里开始", "is_head": head_id is None,
               "children": [k.id for k in kids.get(None, [])], "choices": opening_choices}
    nodes.append({"id": OPENING, "parent_turn_id": None, "branch_id": MAIN, "index": 0, "chapter": 1, "action": "",
                  "option_id": None, "hint": None, "preview": opening["preview"], "created_at": world.created_at,
                  "on_path": True, "is_head": head_id is None, "children": opening["children"], "choices": opening_choices,
                  # 兼容前端草案字段
                  "parent_id": None, "turn_id": None, "summary": _clip(world.opening_scene, 40) or "故事从这里开始", "line_id": MAIN,
                  "current": head_id is None, "choice_id": None})
    for r in rows:
        parent_opts = by_id[r.parent_turn_id].options if r.parent_turn_id in by_id else \
            [o.model_dump() for o in world.opening_options]
        ch = _choice_of(r, parent_opts or [])
        from app.services.repo import turn_option_id
        prev = _clip(r.narration)
        nodes.append({"id": r.id, "parent_turn_id": r.parent_turn_id, "branch_id": r.branch_id or MAIN, "index": r.index,
                      "chapter": r.chapter, "action": r.action, "option_id": turn_option_id(r),
                      "hint": (ch or {}).get("hint") or None, "preview": prev, "created_at": r.created_at.isoformat(),
                      "on_path": bool(r.active), "is_head": r.id == head_id,
                      "children": [k.id for k in kids.get(r.id, [])],
                      "choices": _choices(world, r.options or [], kids.get(r.id, [])),
                      "parent_id": r.parent_turn_id or OPENING, "turn_id": r.id, "summary": _clip(r.narration, 40),
                      "line_id": r.branch_id or MAIN, "current": r.id == head_id, "choice_id": turn_option_id(r)})
    cur_branch = (head.branch_id or MAIN) if head else MAIN
    per: dict[str, list[TurnRow]] = {}
    for r in rows:
        per.setdefault(r.branch_id or MAIN, []).append(r)
    branches = [{"id": MAIN, "label": "主线", "title": world.title, "parent_branch_id": None, "fork_turn_id": None,
                 "fork_index": 0, "turn_count": len(per.get(MAIN, [])),
                 "tip_turn_id": per[MAIN][-1].id if per.get(MAIN) else None, "is_current": cur_branch == MAIN,
                 "created_at": world.created_at}]
    for b in branch_rows(world.id):
        mine = per.get(b.id, [])
        if not mine:
            continue
        branches.append({"id": b.id, "label": f"支线{b.seq}", "title": _clip(mine[0].action, 20),
                         "parent_branch_id": b.parent_branch_id, "fork_turn_id": b.fork_turn_id, "fork_index": b.fork_index,
                         "turn_count": len(mine), "tip_turn_id": mine[-1].id, "is_current": cur_branch == b.id,
                         "created_at": b.created_at.isoformat()})
    return {"world_id": world.id, "head_turn_id": head_id, "branch_id": cur_branch, "opening": opening,
            "branches": branches, "nodes": nodes,
            # 兼容前端草案字段
            "current_node_id": head_id or OPENING,
            "lines": [{"id": b["id"], "leaf_id": b["tip_turn_id"] or OPENING, "current": b["is_current"],
                       "label": b["label"], "title": b["title"]} for b in branches]}


def path(world: World, turn_id: str | None) -> list[Turn]:
    """开局 → 指定节点的回合（升序），只预览不切换。"""
    from app.services import repo
    if turn_id == OPENING:
        return []
    row = get_row(world.id, turn_id) if turn_id else head_row(world)
    if turn_id and row is None:
        raise BranchError(NOT_FOUND)
    rows: list[TurnRow] = []
    seen: set[str] = set()
    while row is not None and row.id not in seen:
        seen.add(row.id)
        rows.append(row)
        row = get_row(world.id, row.parent_turn_id) if row.parent_turn_id else None
    rows.reverse()
    ids = [i for r in rows for i in r.event_ids]
    with session_scope() as s:
        evs = {e.id: repo.event_out(e) for e in s.exec(select(EventRow).where(col(EventRow.id).in_(ids)))} if ids else {}
    return [repo.turn_out(r, [evs[i] for i in r.event_ids if i in evs]) for r in rows]
