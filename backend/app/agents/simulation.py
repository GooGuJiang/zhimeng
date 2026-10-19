"""F3 世界模拟：角色 Agent（焦点 NPC 实时 / 非焦点 NPC 批量）与世界 Agent（时间线 + 全局事件）。

各函数只"决策"，返回结构化结果，不直接写库；由回合图的 persist 节点统一提交（失败不破坏进度）。
LLM 用 fast_model（qwen-turbo）控制成本；无 key / 报错 → 确定性本地兜底。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agents import fallback, prompts
from app.config import get_settings
from app.llm.client import chat_json, llm_enabled
from app.schemas import Character, World


async def _budget(coro: Any, scale: float = 1.0) -> Any:
    """实时 Agent 调用的延迟预算：超时返回 None（调用方走本地规则），保证旁白首字延迟。"""
    try:
        return await asyncio.wait_for(coro, timeout=get_settings().agent_budget_s * scale)
    except asyncio.TimeoutError:
        log.info("agent call over budget (%.1fs), using local rules", get_settings().agent_budget_s)
        return None

log = logging.getLogger("zhimeng.sim")

TIME_SLOTS = ["清晨", "上午", "正午", "午后", "黄昏", "夜晚"]
WORLD_EVENTS = ["城中流言四起，人人都在谈论最近的怪事", "天色骤变，一场大雨即将来临", "有陌生的外来者出现在城门口",
                "市面上某样东西忽然紧俏起来，价格翻了一倍", "官方贴出告示，宵禁提前了一个时辰", "一封没有署名的信在坊间流传"]
OFFSCREEN_VERBS = ["暗中前往{loc}打探消息", "在{loc}与人密谈", "悄悄去了{loc}，似乎在寻找什么", "在{loc}留下了一张字条",
                   "匆匆赶往{loc}，神色凝重", "在{loc}和旁人起了争执"]


def next_time(world: World) -> tuple[str, int]:
    """世界 Agent 的时间线推进：每回合前进一个时段，跨过夜晚则天数 +1。"""
    label = world.state.time.split("·")[-1]
    i = TIME_SLOTS.index(label) if label in TIME_SLOTS else 0
    day = world.state.day
    i += 1
    if i >= len(TIME_SLOTS):
        i, day = 0, day + 1
    return f"第{day}天·{TIME_SLOTS[i]}", day


def pick_focus(world: World, action: str, injected_targets: list[str] | None = None) -> Character | None:
    """焦点 NPC：行动中点名的 > 上帝注入指定的 > 与玩家同处一地的 > 与玩家关系最强的。"""
    npcs = [c for c in world.npcs() if c.status != "离场"]
    if not npcs:
        return None
    named = [c for c in npcs if c.name and c.name in action]
    if named:
        return named[0]
    for cid in injected_targets or []:
        c = world.char(cid)
        if c and not c.is_player:
            return c
    here = [c for c in npcs if c.location_id == world.state.player_location_id]
    if here:
        return here[world.state.turn % len(here)]

    def bond(c: Character) -> int:
        return max((abs(r.affinity) for r in c.relations if r.target_id == "player"), default=0)
    return sorted(npcs, key=bond, reverse=True)[world.state.turn % min(2, len(npcs))]


async def focus_npc_act(world: World, c: Character, action: str, memories: str) -> dict[str, Any]:
    """角色 Agent（焦点，实时）：对玩家行动作出反应。"""
    s = get_settings()
    if llm_enabled():
        d = await _budget(chat_json(prompts.npc_focus_messages(world, c, action, memories), model=s.fast_model,
                            temperature=0.8, max_tokens=400))
        if d and d.get("action"):
            try:
                aff = max(-10, min(10, int(d.get("affinity_delta") or 0)))
            except (TypeError, ValueError):
                aff = 0
            return {"id": c.id, "intent": str(d.get("intent") or "")[:80], "action": str(d["action"])[:120],
                    "line": str(d.get("line") or "")[:120], "mood": str(d.get("mood") or c.mood)[:12],
                    "affinity_delta": aff, "location_id": world.state.player_location_id, "source": "llm"}
    rng = fallback.seed_rng(world.id, world.state.turn, c.id, action)
    goal = c.goals[0] if c.goals else "自己的打算"
    return {"id": c.id, "intent": f"为了{goal}，试探你的来意", "action": rng.choice(fallback.NPC_ACTIONS),
            "line": rng.choice(fallback.NPC_LINES), "mood": rng.choice(["警惕", "好奇", "焦虑", "镇定", "犹豫"]),
            "affinity_delta": rng.randint(-3, 6), "location_id": world.state.player_location_id, "source": "fallback"}


async def batch_npcs_act(world: World, chars: list[Character], recent: str) -> list[dict[str, Any]]:
    """角色 Agent（非焦点，批量/事件驱动）：一次调用驱动多个不在场 NPC，产出场外事件。"""
    if not chars:
        return []
    s = get_settings()
    loc_ids = {l.id for l in world.locations}
    if llm_enabled():
        d = await _budget(chat_json(prompts.npc_batch_messages(world, chars, recent), model=s.fast_model,
                            temperature=0.9, max_tokens=900))
        acts = [a for a in (d or {}).get("actions") or [] if isinstance(a, dict)]
        by_id = {c.id: c for c in chars}
        out = []
        for a in acts:
            c = by_id.get(str(a.get("id")))
            if not c or not a.get("action"):
                continue
            lid = str(a.get("location_id") or "")
            out.append({"id": c.id, "action": str(a["action"])[:120], "mood": str(a.get("mood") or c.mood)[:12],
                        "location_id": lid if lid in loc_ids else c.location_id,
                        "impact": a.get("impact") if a.get("impact") in ("low", "medium", "high") else "low",
                        "source": "llm"})
        if out:
            return out
    out = []
    for c in chars:
        rng = fallback.seed_rng(world.id, world.state.turn, c.id, "offscreen")
        cur = world.loc(c.location_id)
        cands = (cur.connections if cur and cur.connections else [l.id for l in world.locations]) or [None]
        lid = rng.choice(cands + ([c.location_id] if c.location_id else []))
        loc = world.loc(lid)
        goal = c.goals[0] if c.goals else "心中的盘算"
        verb = rng.choice(OFFSCREEN_VERBS).format(loc=loc.name if loc else "某处")
        out.append({"id": c.id, "action": f"{c.name}为了{goal}，{verb}", "mood": rng.choice(["焦虑", "坚定", "警惕", "兴奋", "疲惫"]),
                    "location_id": lid, "impact": rng.choice(["low", "low", "medium", "high"]), "source": "fallback"})
    return out


async def world_agent_tick(world: World, recent: str, with_event: bool) -> dict[str, Any]:
    """世界 Agent：推进时间线；with_event=True 时产生一条全局事件。"""
    time_label, day = next_time(world)
    res: dict[str, Any] = {"time": time_label, "day": day, "event": "", "impact": "low"}
    if not with_event:
        return res
    if llm_enabled():
        d = await _budget(chat_json(prompts.world_agent_messages(world, recent), model=get_settings().fast_model,
                            temperature=0.9, max_tokens=300))
        if d and str(d.get("event") or "").strip():
            res["event"] = str(d["event"])[:120]
            res["impact"] = d.get("impact") if d.get("impact") in ("low", "medium", "high") else "low"
            return res
    rng = fallback.seed_rng(world.id, world.state.turn, "world")
    res["event"] = rng.choice(WORLD_EVENTS)
    res["impact"] = rng.choice(["low", "medium"])
    return res
