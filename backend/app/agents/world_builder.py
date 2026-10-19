"""F1 造化开局 / F10 education: build a structured World from a prompt or source text."""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.agents import fallback, prompts
from app.llm.client import LLMUnavailable, chat_stream, llm_enabled, parse_json
from app.memory import store
from app.schemas import (Character, GenerateWorldRequest, Item, KnowledgeCard, Location, Option,
                         PlayerInfo, World, WorldState)
from app.services import guard, repo

log = logging.getLogger("zhimeng.world")
Event = tuple[str, dict[str, Any]]


def _s(v: Any, default: str = "") -> str:
    return str(v).strip() if v not in (None, "") else default


def normalize_world(data: dict[str, Any], *, world_id: str, req: GenerateWorldRequest, source: str) -> World:
    """Validate/repair model JSON into a consistent World (ids unique, references valid)."""
    locs_in = [l for l in data.get("locations") or [] if isinstance(l, dict)] or \
        fallback.build_world_dict(req.prompt, None, None, "short")["locations"]
    locations: list[Location] = []
    id_map: dict[str, str] = {}
    for i, l in enumerate(locs_in[:10]):
        lid = f"loc_{i + 1}"
        id_map[_s(l.get("id"), lid)] = lid
        id_map[_s(l.get("name"), lid)] = lid
        locations.append(Location(id=lid, name=_s(l.get("name"), f"地点{i + 1}"), description=_s(l.get("description")),
                                  x=float(l.get("x") or (15 + 70 * ((i * 37) % 100) / 100)),
                                  y=float(l.get("y") or (15 + 70 * ((i * 61) % 100) / 100)),
                                  connections=[str(c) for c in l.get("connections") or []],
                                  interactables=[str(c) for c in l.get("interactables") or []][:6]))
    for l in locations:
        l.x, l.y = max(0.0, min(100.0, l.x)), max(0.0, min(100.0, l.y))
        l.connections = sorted({id_map[c] for c in l.connections if c in id_map and id_map[c] != l.id})
    if len(locations) > 1:
        for i, l in enumerate(locations):  # guarantee connectivity
            if not l.connections:
                l.connections = [locations[(i + 1) % len(locations)].id]
    loc_ids = {l.id for l in locations}

    chars_in = [c for c in data.get("characters") or [] if isinstance(c, dict)]
    cmap: dict[str, str] = {"player": "player", "玩家": "player"}
    for i, c in enumerate(chars_in[:10]):
        cmap[_s(c.get("id"), f"c_{i + 1}")] = f"c_{i + 1}"
        cmap[_s(c.get("name"), f"c_{i + 1}")] = f"c_{i + 1}"
    p = data.get("player") or {}
    player = PlayerInfo(name=_s(p.get("name"), "你"), role=_s(p.get("role"), "旅人"), character_id="player")
    start_loc = locations[0].id if locations else None
    characters = [Character(id="player", name=player.name, role=player.role, persona="玩家角色", goals=["由你书写"],
                            location_id=start_loc, mood="好奇", is_player=True, avatar_emoji="🧭")]
    for i, c in enumerate(chars_in[:10]):
        rels = []
        for r in c.get("relations") or []:
            if isinstance(r, dict) and (tid := cmap.get(_s(r.get("target_id")))) and tid != f"c_{i + 1}":
                try:
                    aff = max(-100, min(100, int(r.get("affinity") or 0)))
                except (TypeError, ValueError):
                    aff = 0
                rels.append({"target_id": tid, "type": _s(r.get("type"), "相识"), "affinity": aff})
        lid = id_map.get(_s(c.get("location_id")), None)
        characters.append(Character(id=f"c_{i + 1}", name=_s(c.get("name"), f"角色{i + 1}"), role=_s(c.get("role")),
                                    persona=_s(c.get("persona")), goals=[str(g) for g in c.get("goals") or []][:4],
                                    relations=rels, location_id=lid if lid in loc_ids else (locations[i % len(locations)].id if locations else None),
                                    mood=_s(c.get("mood"), "平静"), avatar_emoji=_s(c.get("avatar_emoji")) or None))
    items = [Item(id=f"it_{i + 1}", name=_s(it.get("name"), f"物品{i + 1}"), description=_s(it.get("description")),
                  owner_id=cmap.get(_s(it.get("owner_id")), None) if it.get("owner_id") else None)
             for i, it in enumerate([x for x in data.get("items") or [] if isinstance(x, dict)][:12])]
    stats = {}
    for k, v in (data.get("stats") or {}).items():
        try:
            stats[str(k)] = int(v)
        except (TypeError, ValueError):
            pass
    opts = [Option(id=f"opt_{i + 1}", text=_s(o.get("text") if isinstance(o, dict) else o))
            for i, o in enumerate((data.get("opening_options") or [])[:4])]
    cards = [KnowledgeCard(id=f"k_{i + 1}", title=_s(k.get("title"), f"知识点{i + 1}"), content=_s(k.get("content")),
                           source=_s(k.get("source")) or None)
             for i, k in enumerate([x for x in data.get("knowledge_cards") or [] if isinstance(x, dict)][:12])]
    world = World(
        id=world_id, title=_s(data.get("title"), "未命名世界")[:30], genre=_s(data.get("genre"), req.genre or ""),
        tone=_s(data.get("tone"), req.tone or ""), era=_s(data.get("era")), setting=_s(data.get("setting")),
        mode=req.mode, language=req.language, premise=_s(data.get("premise"), req.prompt[:120]),
        initial_conflict=_s(data.get("initial_conflict")), opening_scene=_s(data.get("opening_scene")),
        player=player, locations=locations, characters=characters, items=items, knowledge_cards=cards,
        opening_options=opts, state=WorldState(player_location_id=start_loc, stats=stats),
        rating="all" if req.minor_mode else req.rating, minor_mode=req.minor_mode, source=source)  # type: ignore[arg-type]
    if not world.opening_options:
        world.opening_options = [Option(**o) for o in fallback.options_for(world, 0)]
    return world


async def initial_memories(world: World) -> None:
    entries: list[dict[str, Any]] = [
        {"content": f"世界《{world.title}》：{world.setting}", "kind": "setting"},
        {"content": f"初始冲突：{world.initial_conflict}", "kind": "setting"},
        {"content": f"开场：{world.opening_scene}", "kind": "event"},
        {"content": f"玩家身份：{world.player.role}", "kind": "setting"},
    ]
    for c in world.npcs():
        loc = world.loc(c.location_id)
        entries.append({"content": f"{c.name}是{c.role}，{c.persona}；目标：{'、'.join(c.goals)}；常在{loc.name if loc else '未知'}",
                        "kind": "setting", "refs": {"character_id": c.id}})
    for l in world.locations:
        entries.append({"content": f"地点{l.name}：{l.description}", "kind": "setting", "refs": {"location_id": l.id}})
    for it in world.items:
        entries.append({"content": f"物品{it.name}：{it.description}", "kind": "setting"})
    for k in world.knowledge_cards:
        entries.append({"content": f"知识点{k.title}：{k.content}", "kind": "fact", "refs": {"card_id": k.id}})
    for e in entries:
        e.setdefault("turn", 0)
        e.setdefault("chapter", 1)
    await store.add_memories(world.id, entries)


STAGE_KEYS = [("\"locations\"", "locations", "绘制地图：地点与路线", 40), ("\"characters\"", "characters", "唤醒角色：NPC 人格与关系", 55),
              ("\"opening_scene\"", "conflict", "埋下初始冲突与开场", 70), ("\"knowledge_cards\"", "conflict", "整理知识卡", 72)]


async def _draft_with_llm(msgs: list[dict[str, str]], temperature: float, holder: dict[str, Any]) -> AsyncIterator[Event]:
    """流式调用 LLM 起草世界 JSON：边生成边按出现的字段推送进度（加载可视化）；结果放进 holder["data"]。"""
    buf, seen = "", set()
    try:
        async for chunk in chat_stream(msgs, temperature=temperature, max_tokens=3500):
            buf += chunk
            for key, stage, msg, pct in STAGE_KEYS:
                if key in buf and key not in seen:
                    seen.add(key)
                    yield "progress", {"stage": stage, "message": msg, "pct": pct, "percent": pct}
    except LLMUnavailable as e:
        log.warning("world LLM stream failed: %s", e)
        holder["data"] = None
        return
    holder["data"] = parse_json(buf)


async def generate_world_events(req: GenerateWorldRequest, world_id: str | None = None,
                                edu: dict[str, Any] | None = None) -> AsyncIterator[Event]:
    """Async generator of (sse_event, payload). Persists the world before yielding ``world``.

    安全顺序（TEAM.md）：check_input(world_prompt/source_text) → 生成 → check_output(世界文本) → 持久化。
    """
    def prog(stage: str, msg: str, pct: int) -> Event:
        return "progress", {"stage": stage, "message": msg, "pct": pct, "percent": pct}

    yield prog("safety", "正在进行内容安全检查…", 5)
    text_in = "\n".join(x for x in [req.prompt, req.source_text or ""] if x)
    verdict = await guard.check_input(text_in, minor_mode=req.minor_mode, rating=req.rating,
                                      context="source_text" if req.mode == "education" else "world_prompt")
    if verdict.blocked:
        yield "safety", verdict.model_dump()
        yield "done", {"blocked": True, "world_id": None}
        return

    world_id = world_id or repo.new_id("w")
    data: dict[str, Any] | None = None
    source = "fallback"
    if llm_enabled():
        yield prog("outline", "造化中：构思时代背景与基调…", 15)
        if req.mode == "education":
            msgs = prompts.education_messages(req.source_text or req.prompt, (edu or {}).get("title"),
                                              (edu or {}).get("subject"), (edu or {}).get("grade"))
        else:
            msgs = prompts.world_messages(req.prompt, req.genre, req.tone, req.length, req.language, req.minor_mode)
        holder: dict[str, Any] = {}
        async for ev in _draft_with_llm(msgs, 0.9 if req.mode == "story" else 0.4, holder):
            yield ev
        data = holder.get("data")
        if data and (data.get("locations") and data.get("characters")):
            source = "llm"
        else:
            data = None
            yield prog("outline", "模型暂不可用，已切换本地兜底模板", 30)
    else:
        yield prog("outline", "本地兜底模板：构思时代背景与基调…", 20)
    if data is None:
        data = (fallback.build_education_dict(req.source_text or req.prompt, (edu or {}).get("title"), (edu or {}).get("subject"))
                if req.mode == "education" else fallback.build_world_dict(req.prompt, req.genre, req.tone, req.length))
    yield prog("locations", f"绘制地图：{len(data.get('locations') or [])} 个地点", 50)
    yield prog("characters", f"唤醒角色：{len(data.get('characters') or [])} 位 NPC", 65)
    world = normalize_world(data, world_id=world_id, req=req, source=source)
    if req.mode == "education" and not world.knowledge_cards:  # LLM 漏了知识卡 → 用原文兜底
        fb = fallback.build_education_dict(req.source_text or req.prompt, (edu or {}).get("title"), (edu or {}).get("subject"))
        world.knowledge_cards = [KnowledgeCard(**k) for k in fb["knowledge_cards"]]
    yield prog("conflict", "埋下初始冲突与伏笔", 75)

    out = await guard.check_output(json.dumps(world.model_dump(include={"title", "setting", "initial_conflict", "opening_scene"}),
                                              ensure_ascii=False), minor_mode=req.minor_mode, rating=req.rating)
    if out.blocked:
        log.warning("world output blocked, using fallback template")
        yield "safety", out.model_dump()
        world = normalize_world(fallback.build_world_dict("", None, None, req.length), world_id=world_id, req=req, source="fallback")
        source = "fallback"
    world.opening_scene = guard.filter_chunk(world.opening_scene, minor_mode=req.minor_mode)
    world.setting = guard.filter_chunk(world.setting, minor_mode=req.minor_mode)
    world.initial_conflict = guard.filter_chunk(world.initial_conflict, minor_mode=req.minor_mode)
    world.state.flags["gen_request"] = req.model_dump()
    if edu:
        world.state.flags["edu"] = edu

    yield prog("persist", "写入世界存档", 85)
    existing = repo.load_world(world_id)
    if existing:  # regenerate in place: wipe old content (same id)
        world.created_at = existing.created_at
        repo.delete_world(world_id)
    repo.save_world(world)
    for c in world.npcs():  # 轨迹起点（上帝视角）
        repo.add_trajectory(world.id, c.id, 0, c.location_id, f"登场：{c.role}", c.mood)
    yield prog("memory", "构建世界记忆库", 95)
    await initial_memories(world)
    yield "world", world.model_dump(mode="json")
    yield prog("done", "世界已生成", 100)
    yield "done", {"world_id": world.id, "source": source}
