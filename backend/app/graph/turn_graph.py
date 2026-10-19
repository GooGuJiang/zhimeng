"""F2/F3/F4 回合图（LangGraph）：一次玩家行动 = 一次多智能体协作。

    safety_in ─(blocked)→ END
        │
      memory ──┬── world_agent ──┐        (世界 Agent：时间线 + 全局事件)
               └── npc_agents  ──┴→ director → extract → persist → END
                    (角色 Agent：焦点 NPC 实时；非焦点 NPC 每 N 回合/事件驱动批量)

- 导演 Agent（director）把记忆、焦点 NPC 意图、场外事件、上帝注入编织成流式叙事。
- 所有节点只修改内存中的世界副本；persist 节点统一提交 → 任何一步失败都不破坏已有进度（可重试）。
- 安全顺序（TEAM.md）：check_input → 每个流式片段 filter_chunk → 全文 check_output → 持久化 filtered_text。
- 多模态（插画+配音）只在关键场景调用（开局/章节边界/注入或高影响事件/结局），由 run_turn 在 persist 后触发。
SSE 事件顺序：progress → memory → event → token* → options → ui → asset* → done。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app import multimodal
from app.agents import director, fallback, simulation
from app.config import get_settings
from app.db import TurnRow, session_scope, utcnow
from app.memory import store
from app.schemas import AI_LABEL, Citation, Item, KnowledgeCard, Option, Turn, TurnRequest, World, WorldEvent
from app.services import guard, repo
from app.ui.components import build_components

log = logging.getLogger("zhimeng.turn")
Emit = Callable[[str, Any], Awaitable[None]]
_locks: dict[str, asyncio.Lock] = {}
_bg: set[asyncio.Task] = set()


def world_lock(world_id: str) -> asyncio.Lock:
    return _locks.setdefault(world_id, asyncio.Lock())


def chapter_of(index: int) -> int:
    return (max(1, index) - 1) // get_settings().chapter_size + 1


class TurnCtx:
    """一次回合的可变上下文（不进 LangGraph 状态合并，只在节点间共享）。"""

    def __init__(self, world: World, action: str, *, option_id: str | None, client_turn_id: str | None,
                 replace_index: int | None, reused_inject_ids: list[str], emit: Emit):
        self.snapshot = world.model_dump(mode="json")  # 回合前快照（重试用）
        self.world = world
        self.action = action
        self.option_id = option_id
        self.client_turn_id = client_turn_id
        self.replace_index = replace_index
        self.index = replace_index or world.state.turn + 1
        self.chapter = chapter_of(self.index)
        self.emit = emit
        self.injects = _injections(world.id, reused_inject_ids)
        # 上帝视角手动推进（tick）在上一回合之后产生的事件：编入本回合叙事；重试时同样可见
        self.ticks = repo.tick_events_since(world.id, world.state.turn)
        if replace_index:  # 重试：快照早于 tick，把 tick 造成的 NPC 位置/情绪变化重新应用
            for r in self.ticks:
                c = world.char(r.actor_ids[0]) if r.actor_ids else None
                if c and not c.is_player and r.location_id:
                    c.location_id = r.location_id
        self.prev_options = current_options(world)
        self.events: list[WorldEvent] = []
        self.npc_updates: list[dict[str, Any]] = []
        self.focus = None
        self.narration = ""
        self.extraction: dict[str, Any] = {}
        self.options: list[Option] = []
        self.turn: Turn | None = None
        self.moved = False
        self.arrived: str | None = None
        self.recent = ""
        self.tasks: dict[str, asyncio.Task[Any]] = {}


class TurnState(TypedDict, total=False):
    ctx: TurnCtx
    blocked: bool
    citations: list[Citation]
    world_tick: dict[str, Any]
    npc_done: bool
    narrated: bool
    extracted: bool
    committed: bool


def _injections(world_id: str, reused_ids: list[str]) -> list[Any]:
    rows = {r.id: r for r in repo.pending_injections(world_id)}
    if reused_ids:
        from sqlmodel import col, select

        from app.db import EventRow
        with session_scope() as s:
            for r in s.exec(select(EventRow).where(col(EventRow.id).in_(reused_ids))):
                rows[r.id] = r
    return sorted(rows.values(), key=lambda r: r.timestamp)


def current_options(world: World) -> list[Option]:
    row = repo.get_turn_row(world.id, index=world.state.turn) if world.state.turn > 0 else None
    if row:
        return [Option(**o) for o in row.options]
    return list(world.opening_options)


async def _progress(ctx: TurnCtx, stage: str, message: str, pct: int) -> None:
    await ctx.emit("progress", {"stage": stage, "message": message, "pct": pct, "percent": pct})


def _ev(ctx: TurnCtx, type_: str, summary: str, actors: list[str], loc: str | None, impact: str,
        in_world_time: str) -> WorldEvent:
    return WorldEvent(id=repo.new_id("ev"), world_id=ctx.world.id, type=type_, summary=summary, actor_ids=actors,
                      location_id=loc, turn=ctx.index, chapter=ctx.chapter, impact=impact,
                      timestamp=utcnow().isoformat(), in_world_time=in_world_time)


# ---------------------------------------------------------------- nodes
def _prepare(ctx: TurnCtx) -> None:
    """叙事前的同步准备：行动里的目的地先生效（叙事/焦点 NPC 以新地点为准）、最近剧情、焦点 NPC。"""
    w = ctx.world
    dest = fallback.detect_location(w, ctx.action)
    if dest and dest != w.state.player_location_id:
        w.state.player_location_id, ctx.moved = dest, True
        if p := w.char("player"):
            p.location_id = dest
        ctx.arrived = dest
    turns = [t for t in repo.list_turns(w.id, limit=4) if t.index < ctx.index][-3:]
    sums = [s for s in repo.list_summaries(w.id) if s.to_turn < ctx.index]
    parts = [f"【前情提要】{sums[-1].summary}"] if sums else []
    parts += [f"[第{t.index}回合] 你：{t.action}\n{t.narration[:220]}" for t in turns]
    ctx.recent = "\n".join(parts) if parts else f"开场：{w.opening_scene[:200]}"
    targets = [t for r in ctx.injects for t in (r.actor_ids or [])]
    ctx.focus = simulation.pick_focus(w, ctx.action, targets)


async def _npc_job(ctx: TurnCtx) -> list[dict[str, Any]]:
    """角色 Agent：焦点 NPC 每回合实时；其余 NPC 每 N 回合批量，或有高影响注入时事件驱动推进。"""
    w, focus = ctx.world, ctx.focus
    jobs = []
    if focus:
        mems = "；".join(m.content for m in store.list_memories(w.id, limit=200)
                        if (m.refs or {}).get("character_id") == focus.id and m.turn < ctx.index)[:600]

        async def focus_job() -> list[dict[str, Any]]:
            fa = await simulation.focus_npc_act(w, focus, ctx.action, mems)
            fa["focus"] = True
            return [fa]
        jobs.append(focus_job())
    every = max(1, get_settings().npc_batch_every)
    event_driven = any(r.impact == "high" for r in ctx.injects)
    if (ctx.index - 1) % every == 0 or event_driven:
        others = [c for c in w.npcs() if not focus or c.id != focus.id]
        jobs.append(simulation.batch_npcs_act(w, others, ctx.recent))
    return [u for part in await asyncio.gather(*jobs) for u in part]


def _start_prefetch(ctx: TurnCtx) -> None:
    """与输入审核并行启动：记忆检索、世界 Agent、角色 Agent（都只产出内部数据，审核通过前不向前端推送任何内容；
    被拦截则取消）。首字延迟 ≈ max(审核, 检索+Agent 预算) + 旁白首 token。"""
    _prepare(ctx)
    w = ctx.world
    loc = w.loc(w.state.player_location_id)
    query = f"{ctx.action} {loc.name if loc else ''} " + " ".join(r.summary for r in ctx.injects)
    every = max(1, get_settings().npc_batch_every)
    ctx.tasks = {
        "memory": asyncio.create_task(store.search(w.id, query, top_k=5, before_turn=ctx.index)),
        "world": asyncio.create_task(simulation.world_agent_tick(w, ctx.recent, with_event=ctx.index % every == 0)),
        "npcs": asyncio.create_task(_npc_job(ctx)),
    }


def _cancel_prefetch(ctx: TurnCtx) -> None:
    for t in getattr(ctx, "tasks", {}).values():
        t.cancel()


async def node_safety(state: TurnState) -> TurnState:
    ctx = state["ctx"]
    await _progress(ctx, "safety", "内容安全检查…", 5)
    _start_prefetch(ctx)
    try:
        v = await guard.check_input(ctx.action, minor_mode=ctx.world.minor_mode, rating=ctx.world.rating, context="turn")
    except BaseException:
        _cancel_prefetch(ctx)
        raise
    if v.blocked:
        _cancel_prefetch(ctx)
        await ctx.emit("safety", v.model_dump())
        return {"blocked": True}
    if v.crisis or v.categories:  # 放行但提示（如危机提示语）
        await ctx.emit("safety", v.model_dump())
    return {"blocked": False}


async def node_memory(state: TurnState) -> TurnState:
    """F4：生成前先检索已发生事实（向量 + 结构化），并整理最近剧情与章节摘要（检索已在审核时并行启动）。"""
    ctx = state["ctx"]
    await _progress(ctx, "memory", "翻阅世界记忆…", 15)
    cites = await ctx.tasks["memory"]
    await ctx.emit("memory", {"facts": [c.model_dump() for c in cites]})
    return {"citations": cites}


async def node_world(state: TurnState) -> TurnState:
    ctx = state["ctx"]
    await _progress(ctx, "world", "世界 Agent 推进时间线…", 25)
    return {"world_tick": await ctx.tasks["world"]}


async def node_npcs(state: TurnState) -> TurnState:
    ctx = state["ctx"]
    await _progress(ctx, "npc", "角色们各自盘算…", 35)
    ctx.npc_updates = await ctx.tasks["npcs"]
    return {"npc_done": True}


async def node_director(state: TurnState) -> TurnState:
    ctx = state["ctx"]
    w = ctx.world
    tick = state.get("world_tick") or {}
    time_label = tick.get("time") or w.state.time
    names = {c.id: c.name for c in w.characters}
    # 汇总本回合事件（F3）：注入 / 世界 / 场外 / 焦点 NPC 行动
    for r in ctx.injects:
        ctx.events.append(WorldEvent(id=r.id, world_id=w.id, type="injected", summary=r.summary, actor_ids=r.actor_ids,
                                     location_id=r.location_id, turn=r.turn, chapter=r.chapter, impact=r.impact,
                                     timestamp=r.timestamp.isoformat(), in_world_time=r.in_world_time, seen=r.seen))
    for r in ctx.ticks:  # 已落库的手动推进事件（不重复写入）
        ctx.events.append(repo.event_out(r))
    if tick.get("event"):
        ctx.events.append(_ev(ctx, "world", tick["event"], [], None, tick.get("impact", "low"), time_label))
    focus_line = ""
    for u in ctx.npc_updates:
        if u.get("focus"):
            focus_line = f"{names.get(u['id'])}的意图：{u.get('intent')}；行动：{u.get('action')}；台词：“{u.get('line')}”"
            ctx.events.append(_ev(ctx, "npc_action", f"{names.get(u['id'])}{u['action']}"
                                  if not str(u["action"]).startswith(names.get(u["id"], "?")) else u["action"],
                                  [u["id"]], u.get("location_id"), "low", time_label))
        else:
            ctx.events.append(_ev(ctx, "offscreen", u["action"], [u["id"]], u.get("location_id"),
                                  u.get("impact", "low"), time_label))
    await ctx.emit("event", {"events": [e.model_dump() for e in ctx.events]})

    await _progress(ctx, "director", "导演 Agent 编排叙事…", 45)
    cites: list[Citation] = state.get("citations") or []
    memory_ctx = "\n".join(f"- （{c.source}）{c.content}" for c in cites)
    off = [e for e in ctx.events if e.type in ("offscreen", "world")]
    events_ctx = "\n".join(f"- {e.summary}" for e in off)
    inject_ctx = "\n".join(f"- {r.summary}（影响：{r.impact}）" for r in ctx.injects)
    await _progress(ctx, "narrate", "落笔成文…", 55)
    cf = guard.ChunkFilter(minor_mode=w.minor_mode)
    raw: list[str] = []
    delay = get_settings().stream_delay
    async for src, chunk in director.narrate_stream(
            w, ctx.action, memory_ctx=memory_ctx, recent=ctx.recent, npc_ctx=focus_line, events_ctx=events_ctx,
            inject_ctx=inject_ctx, focus=ctx.focus, event_lines=[e.summary for e in off],
            injects=[r.summary for r in ctx.injects], turn=ctx.index):
        raw.append(chunk)
        out = cf.feed(chunk)
        if out:
            await ctx.emit("token", {"text": out})
        if src == "fallback" and delay:
            await asyncio.sleep(delay)
    tail = cf.flush()
    if tail:
        await ctx.emit("token", {"text": tail})
    ctx.narration = "".join(raw).strip()
    return {"narrated": True}


async def node_extract(state: TurnState) -> TurnState:
    ctx = state["ctx"]
    w = ctx.world
    await _progress(ctx, "extract", "提取关键事实，校验一致性…", 80)
    verdict = await guard.check_output(ctx.narration, minor_mode=w.minor_mode, rating=w.rating)
    # 流式分片可能切开敏感词（filter_chunk 拦不住）→ 入库/返回的叙事一律用全文 check_output 的 filtered_text
    if verdict.blocked:
        await ctx.emit("safety", verdict.model_dump())
        ctx.narration = guard.SAFE_NOTICE
    else:
        ctx.narration = verdict.filtered_text if verdict.filtered_text is not None else ctx.narration
    ex = await director.extract(w, ctx.action, ctx.narration, ctx.focus)
    if ctx.arrived and (loc := w.loc(ctx.arrived)):
        ex.setdefault("facts", []).append(f"你来到了{loc.name}")
    ctx.extraction = ex
    _apply(ctx, state.get("world_tick") or {}, ex)
    return {"extracted": True}


def _apply(ctx: TurnCtx, tick: dict[str, Any], ex: dict[str, Any]) -> None:
    """把各 Agent 的决策应用到世界副本（尚未落库）。"""
    w = ctx.world
    st = w.state
    loc_ids = {l.id for l in w.locations}
    st.turn, st.chapter = ctx.index, ctx.chapter
    if tick.get("time"):
        st.time, st.day = tick["time"], tick.get("day", st.day)
    lid = ex.get("player_location_id")
    if lid in loc_ids and lid != st.player_location_id:
        st.player_location_id, ctx.moved = lid, True
        if p := w.char("player"):
            p.location_id = lid
    try:
        st.hp = max(0, min(100, st.hp + int(ex.get("hp_delta") or 0)))
    except (TypeError, ValueError):
        pass
    for k, v in (ex.get("stats_delta") or {}).items():
        try:
            st.stats[str(k)] = max(0, min(100, st.stats.get(str(k), 0) + int(v)))
        except (TypeError, ValueError):
            continue
    for it in ex.get("items_gained") or []:
        name = str((it or {}).get("name") or "").strip() if isinstance(it, dict) else str(it)
        if name and not any(i.name == name and i.owner_id == "player" for i in w.items):
            w.items.append(Item(id=f"it_{len(w.items) + 1}_{ctx.index}", name=name[:20],
                                description=str((it or {}).get("description") or "") if isinstance(it, dict) else "",
                                owner_id="player"))
    lost = {str(x) for x in ex.get("items_lost") or []}
    w.items = [i for i in w.items if not (i.owner_id == "player" and i.name in lost)]
    # NPC 决策（角色 Agent）+ 抽取器的角色更新
    for u in ctx.npc_updates + [dict(x, source="extract") for x in ex.get("character_updates") or [] if isinstance(x, dict)]:
        c = w.char(str(u.get("id")))
        if not c or c.is_player:
            continue
        if u.get("mood"):
            c.mood = str(u["mood"])[:12]
        if u.get("location_id") in loc_ids:
            c.location_id = u["location_id"]
        try:
            d = int(u.get("affinity_delta") or 0)
        except (TypeError, ValueError):
            d = 0
        if d:
            rel = next((r for r in c.relations if r.target_id == "player"), None)
            if rel:
                rel.affinity = max(-100, min(100, rel.affinity + d))
    for k in ex.get("knowledge_cards") or []:
        if isinstance(k, dict) and k.get("title") and k.get("content") and w.mode == "education":
            w.knowledge_cards.append(KnowledgeCard(id=f"k_{len(w.knowledge_cards) + 1}", title=str(k["title"])[:30],
                                                   content=str(k["content"])[:300], source=k.get("source"), turn=ctx.index))
    if ex.get("ending"):
        st.flags["ending"] = str(ex["ending"])[:200]
    # 选项：抽取器给出的 → 否则模板；保证与上一回合不同
    opts = []
    for i, o in enumerate((ex.get("options") or [])[:4]):
        text = (o.get("text") if isinstance(o, dict) else str(o)) or ""
        if text.strip():
            opts.append(Option(id=f"opt_{i + 1}", text=text.strip()[:40], hint=(o.get("hint") if isinstance(o, dict) else None)))
    if len(opts) < 2:
        opts = [Option(**o) for o in fallback.options_for(w, ctx.index)]
    prev = [o.text for o in ctx.prev_options]
    if [o.text for o in opts] == prev:
        opts[-1] = Option(id=opts[-1].id, text=f"回想刚才{ctx.focus.name if ctx.focus else '发生'}的话" if ctx.focus else "回想刚才发生的一切")
    ctx.options = opts


async def node_persist(state: TurnState) -> TurnState:
    """统一提交：回合、事件、轨迹、记忆、世界状态；失败则回滚到回合前快照。"""
    ctx = state["ctx"]
    w = ctx.world
    await _progress(ctx, "persist", "写入世界存档…", 90)
    snapshot_world = World.model_validate(ctx.snapshot)
    if ctx.replace_index:  # 重试：成功生成后才替换旧的最后一回合
        repo.rollback_from_turn(w.id, ctx.index)
    inject_ids = [r.id for r in ctx.injects]
    key = multimodal.is_key_scene(ctx.index, [e.model_dump() for e in ctx.events],
                                  ending=bool(ctx.extraction.get("ending")))
    turn_id = repo.new_id("t")
    try:
        names = {c.id: c.name for c in w.characters}
        tick_ids = {r.id for r in ctx.ticks}
        for e in ctx.events:
            if e.type != "injected" and e.id not in tick_ids:
                repo.add_event(w.id, id=e.id, type=e.type, summary=e.summary, actor_ids=e.actor_ids,
                               location_id=e.location_id, turn=e.turn, chapter=e.chapter, impact=e.impact,
                               in_world_time=e.in_world_time)
        repo.mark_events(inject_ids, consumed=True)
        for u in ctx.npc_updates:
            c = w.char(u["id"])
            if c:
                repo.add_trajectory(w.id, c.id, ctx.index, c.location_id, str(u.get("action"))[:120], c.mood)
        facts = [str(f) for f in ctx.extraction.get("facts") or []]
        with session_scope() as s:
            s.add(TurnRow(id=turn_id, world_id=w.id, index=ctx.index, chapter=ctx.chapter, action=ctx.action,
                          narration=ctx.narration, options=[o.model_dump() for o in ctx.options], facts=facts,
                          event_ids=[e.id for e in ctx.events], key_scene=key, client_turn_id=ctx.client_turn_id,
                          state_before={"world": ctx.snapshot, "consumed": inject_ids, "option_id": ctx.option_id}))
        base = {"turn": ctx.index, "chapter": ctx.chapter}
        mems = [{"content": f"第{ctx.index}回合，你{fallback.second_person(ctx.action)}。{ctx.narration[:100]}", "kind": "event",
                 **base, "refs": {"turn_id": turn_id}}]
        mems += [{"content": f, "kind": "fact", **base, "refs": {"turn_id": turn_id}} for f in facts]
        mems += [{"content": f"{names.get(e.actor_ids[0], '') + '：' if e.actor_ids and not e.summary.startswith(names.get(e.actor_ids[0], '?')) else ''}{e.summary}",
                  "kind": "event", **base, "refs": {"event_id": e.id, **({"character_id": e.actor_ids[0]} if e.actor_ids else {})}}
                 for e in ctx.events if e.type != "injected" and e.id not in tick_ids]
        await store.add_memories(w.id, mems)
        if w.status == "draft":
            w.status = "active"
        repo.save_world(w)
    except Exception:
        log.exception("persist failed → rollback to pre-turn snapshot")
        repo.rollback_from_turn(w.id, ctx.index)
        repo.mark_events(inject_ids, consumed=False)
        repo.save_world(snapshot_world)
        raise
    # 章节末：摘要压缩（失败不影响本回合）
    if ctx.index % get_settings().chapter_size == 0:
        try:
            await _compress_chapter(w, ctx.chapter)
        except Exception:  # noqa: BLE001
            log.exception("chapter summary failed")
    row = repo.get_turn_row(w.id, turn_id=turn_id)
    ctx.turn = repo.turn_out(row, ctx.events)  # type: ignore[arg-type]
    await ctx.emit("options", {"options": [o.model_dump() for o in ctx.options]})
    comps = build_components(w, events=repo.list_events(w.id, limit=8), options=ctx.options, moved=ctx.moved)
    await ctx.emit("ui", {"components": comps})
    return {"committed": True}


async def _compress_chapter(world: World, chapter: int) -> None:
    turns = [t for t in repo.list_turns(world.id, limit=1000) if t.chapter == chapter]
    if not turns or any(s.chapter == chapter for s in repo.list_summaries(world.id)):
        return
    text = await director.chapter_summary(world, chapter, turns)
    v = await guard.check_output(text, minor_mode=world.minor_mode, rating=world.rating)
    text = v.filtered_text or text
    repo.add_summary(world.id, chapter, turns[0].index, turns[-1].index, text)
    await store.add_memories(world.id, [{"content": text, "kind": "summary", "turn": turns[-1].index,
                                         "chapter": chapter, "refs": {"chapter": chapter}}])


# ---------------------------------------------------------------- graph
def build_graph():
    g = StateGraph(TurnState)
    g.add_node("safety_in", node_safety)
    g.add_node("memory", node_memory)
    g.add_node("world_agent", node_world)
    g.add_node("npc_agents", node_npcs)
    g.add_node("director", node_director)
    g.add_node("extract", node_extract)
    g.add_node("persist", node_persist)
    g.add_edge(START, "safety_in")
    g.add_conditional_edges("safety_in", lambda s: "end" if s.get("blocked") else "go", {"end": END, "go": "memory"})
    g.add_edge("memory", "world_agent")
    g.add_edge("memory", "npc_agents")
    g.add_edge(["world_agent", "npc_agents"], "director")
    g.add_edge("director", "extract")
    g.add_edge("extract", "persist")
    g.add_edge("persist", END)
    return g.compile()


GRAPH = build_graph()


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


async def key_scene_media(world: World, turn: Turn, narration: str, emit: Emit | None = None,
                          wait_s: float = 45.0) -> list[Any]:
    """关键场景：插画 + 配音（multimodal 接口，内部缓存/降级）。超时则转后台继续，完成后补写 asset_ids。"""
    loc = world.loc(world.state.player_location_id)

    async def job() -> list[Any]:
        # key_scene_assets 从 world["minor_mode"] 读取未成年人模式（插画负面词更严格）
        assets = await multimodal.key_scene_assets(world.model_dump(mode="json"), narration, turn_id=turn.id,
                                                   location=loc.name if loc else None)
        if not any(a.type == "audio" for a in assets):  # 远程 TTS 不可用 → 占位音频（prompt 可供 Web Speech 朗读）
            assets.append(await multimodal.speak(world.id, narration[:200], voice="narrator", turn_id=turn.id))
        with session_scope() as s:
            row = s.get(TurnRow, turn.id)
            if row:
                row.asset_ids = list(dict.fromkeys(list(row.asset_ids) + [a.id for a in assets]))
                s.add(row)
        return assets

    task = asyncio.ensure_future(job())
    try:
        assets = await asyncio.wait_for(asyncio.shield(task), timeout=wait_s)
    except asyncio.TimeoutError:
        _bg.add(task)
        task.add_done_callback(_bg.discard)
        return []
    except Exception:  # noqa: BLE001
        log.exception("key scene media failed")
        return []
    if emit:
        for a in assets:
            await emit("asset", a.model_dump())
    turn.asset_ids = [a.id for a in assets]
    return assets


async def run_turn(world_id: str, req: TurnRequest | None, *, retry: bool = False) -> AsyncIterator[tuple[str, Any]]:
    """SSE 事件生成器。图在后台任务中运行（客户端断开也会完成并提交，之后可用 client_turn_id 取回）。"""
    q: asyncio.Queue = asyncio.Queue()
    END_MARK = object()

    async def emit(name: str, data: Any) -> None:
        await q.put((name, data))

    async def runner() -> None:
        try:
            async with world_lock(world_id):
                await _run(world_id, req, retry, emit)
        except Exception as e:  # noqa: BLE001
            log.exception("turn failed")
            await emit("error", {"message": f"本回合生成失败（{type(e).__name__}），进度未受影响，请重试", "retryable": True})
        finally:
            await q.put(END_MARK)

    task = asyncio.create_task(runner())
    _bg.add(task)
    task.add_done_callback(_bg.discard)
    while True:
        item = await q.get()
        if item is END_MARK:
            break
        yield item


async def _run(world_id: str, req: TurnRequest | None, retry: bool, emit: Emit) -> None:
    world = repo.load_world(world_id)
    if not world:
        await emit("error", {"message": "世界不存在", "retryable": False})
        return
    reused: list[str] = []
    replace = None
    if retry:
        last = repo.last_turn_row(world_id)
        if not last:
            await emit("error", {"message": "还没有可重试的回合", "retryable": False})
            return
        world = World.model_validate(last.state_before["world"])
        reused = list(last.state_before.get("consumed") or [])
        replace = last.index
        req = TurnRequest(action=last.action, option_id=last.state_before.get("option_id"),
                          client_turn_id=last.client_turn_id)
    assert req is not None
    if not retry and req.client_turn_id:
        row = repo.get_turn_row(world_id, client_turn_id=req.client_turn_id)
        if row:  # 幂等：已提交 → 直接返回
            t = repo.list_turns(world_id, limit=10_000)
            turn = next(x for x in t if x.id == row.id)
            await emit("done", {"turn": turn.model_dump(), "state": world.state.model_dump(), "idempotent": True})
            return
    action = req.action.strip()
    if req.option_id and not action:
        action = next((o.text for o in current_options(world) if o.id == req.option_id), action)
    ctx = TurnCtx(world, action, option_id=req.option_id, client_turn_id=req.client_turn_id,
                  replace_index=replace, reused_inject_ids=reused, emit=emit)
    try:
        out = await GRAPH.ainvoke({"ctx": ctx})
    finally:
        _cancel_prefetch(ctx)  # 失败/拦截时回收并行预取任务
    if out.get("blocked"):
        await emit("done", {"blocked": True})
        return
    turn = ctx.turn
    assert turn is not None
    if turn.key_scene:
        await key_scene_media(ctx.world, turn, ctx.narration, emit)
    await emit("done", {"turn": turn.model_dump(), "state": ctx.world.state.model_dump()})


# ---------------------------------------------------------------- god tick (F7)
async def god_tick(world_id: str) -> list[WorldEvent]:
    """手动运行一次世界 Agent + 全部 NPC 角色 Agent（不产生玩家回合）。"""
    async with world_lock(world_id):
        w = repo.load_world(world_id)
        if not w:
            raise KeyError(world_id)
        turns = repo.list_turns(world_id, limit=2)
        recent = "\n".join(f"你：{t.action}。{t.narration[:150]}" for t in turns) or w.opening_scene[:200]
        tick, acts = await asyncio.gather(simulation.world_agent_tick(w, recent, with_event=True),
                                          simulation.batch_npcs_act(w, w.npcs(), recent))
        w.state.time, w.state.day = tick["time"], tick["day"]
        t, ch = w.state.turn, w.state.chapter
        events: list[WorldEvent] = []
        if tick.get("event"):
            events.append(repo.add_event(w.id, type="world", summary=tick["event"], actor_ids=[], location_id=None,
                                         turn=t, chapter=ch, impact=tick.get("impact", "low"), in_world_time=w.state.time,
                                         origin="tick"))
        for a in acts:
            c = w.char(a["id"])
            if not c:
                continue
            c.mood = a.get("mood") or c.mood
            c.location_id = a.get("location_id") or c.location_id
            events.append(repo.add_event(w.id, type="offscreen", summary=a["action"], actor_ids=[c.id],
                                         location_id=c.location_id, turn=t, chapter=ch, impact=a.get("impact", "low"),
                                         in_world_time=w.state.time, origin="tick"))
            repo.add_trajectory(w.id, c.id, t, c.location_id, a["action"][:120], c.mood, origin="tick")
        await store.add_memories(w.id, [{"content": e.summary, "kind": "event", "turn": t, "chapter": ch,
                                         "refs": {"event_id": e.id, "origin": "tick", **({"character_id": e.actor_ids[0]} if e.actor_ids else {})}}
                                        for e in events])
        repo.save_world(w)
        return events


def spawn_opening_media(world: World) -> None:
    """确认世界后：开局关键场景自动生成插画 + 旁白配音（后台并行，不阻塞 confirm 响应）。

    两者都以 ``turn_id=None`` 落库（``GET /api/worlds/{id}/assets`` 中 turn_id 为 null 的行）。配音文本 = opening_scene
    先过 check_output（按世界的未成年人模式/分级），被拦截则不配音。若第二步补全在确认之后改写了开场，会再生成一组，
    前端取 turn_id=null 中最新的 image / audio 即可。
    """
    async def image() -> None:
        try:
            loc = world.loc(world.state.player_location_id)
            prompt = multimodal.build_scene_prompt(world.model_dump(mode="json"), world.opening_scene,
                                                   loc.name if loc else None, world.minor_mode)
            await multimodal.illustrate(world.id, prompt, minor_mode=world.minor_mode)
        except Exception:  # noqa: BLE001
            log.exception("opening illustration failed")

    async def audio() -> None:
        try:
            text = (world.opening_scene or "").strip()
            if not text:
                return
            r = await guard.check_output(text, minor_mode=world.minor_mode, rating=world.rating)
            if r.blocked:
                log.warning("opening narration blocked by check_output; skip tts")
                return
            await multimodal.speak(world.id, (r.filtered_text or text)[:600], voice="narrator", turn_id=None)
        except Exception:  # noqa: BLE001
            log.exception("opening narration failed")

    async def job() -> None:
        await asyncio.gather(image(), audio())
    _spawn(job())


__all__ = ["run_turn", "god_tick", "spawn_opening_media", "GRAPH", "AI_LABEL", "world_lock", "chapter_of"]
