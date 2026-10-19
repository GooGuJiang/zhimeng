"""F1 造化开局 / F10 education: build a structured World from a prompt or source text."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.agents import fallback, prompts
from app.config import get_settings
from app.llm.client import LLMUnavailable, chat_json, chat_stream, llm_enabled, parse_json
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


SKELETON_KEYS = [("\"locations\"", "locations", "绘制地图：地点与路线", 40), ("\"characters\"", "characters", "唤醒角色", 55),
                 ("\"initial_conflict\"", "conflict", "埋下初始冲突", 65)]
ENRICH_TIMEOUT = 150.0
_bg: set[asyncio.Task] = set()


def _prog(stage: str, msg: str, pct: int) -> Event:
    return "progress", {"stage": stage, "message": msg, "pct": pct, "percent": pct}


async def _stream_skeleton(msgs: list[dict[str, str]], holder: dict[str, Any]) -> AsyncIterator[Event]:
    """第一步：快速模型流式起草骨架 JSON，按出现的字段推送进度；结果放进 holder。"""
    buf, seen = "", set()
    meta: dict[str, Any] = {}
    try:
        async for chunk in chat_stream(msgs, model=get_settings().skeleton_model, temperature=0.9, max_tokens=900, meta=meta):
            buf += chunk
            for key, stage, msg, pct in SKELETON_KEYS:
                if key in buf and key not in seen:
                    seen.add(key)
                    yield _prog(stage, msg, pct)
    except LLMUnavailable as e:
        log.warning("skeleton LLM failed: %s", e)
        return
    holder["data"], holder["model"] = parse_json(buf), meta.get("model")


def skeleton_to_data(sk: dict[str, Any], req: GenerateWorldRequest, edu: dict[str, Any] | None) -> dict[str, Any]:
    """骨架 → 完整可玩世界数据：缺失字段按本地规则补齐（坐标、连通、性格、目标、关系、物品、属性、开场）。"""
    if req.mode == "education":
        base = fallback.build_education_dict(req.source_text or req.prompt, (edu or {}).get("title"), (edu or {}).get("subject"))
    else:
        base = fallback.build_world_dict(req.prompt, req.genre, req.tone, req.length)
    rng = fallback.seed_rng(req.prompt, "skeleton")
    data = dict(base)
    for k in ("title", "genre", "tone", "era", "setting", "initial_conflict"):
        if _s(sk.get(k)):
            data[k] = _s(sk[k])
    data["premise"] = req.prompt[:120] or data.get("premise", "")
    p = sk.get("player") if isinstance(sk.get("player"), dict) else {}
    data["player"] = {"name": _s(p.get("name"), "你"), "role": _s(p.get("role"), base["player"]["role"])}
    locs_in = [l for l in sk.get("locations") or [] if isinstance(l, dict) and _s(l.get("name"))][:8]
    if len(locs_in) >= 2:
        n = len(locs_in)
        pos = fallback._layout(min(n, 7), rng) + [(rng.uniform(10, 90), rng.uniform(10, 90)) for _ in range(max(0, n - 7))]
        base_locs = base["locations"]
        data["locations"] = [{
            "id": f"loc_{i + 1}", "name": _s(l["name"])[:12], "description": _s(l.get("description")),
            "x": round(pos[i][0], 1), "y": round(pos[i][1], 1),
            "connections": [f"loc_{j + 1}" for j in range(n) if j != i and (abs(j - i) == 1 or {i, j} == {0, n - 1})],
            "interactables": base_locs[i % len(base_locs)]["interactables"] if base_locs else []}
            for i, l in enumerate(locs_in)]
    by_name = {l["name"]: l["id"] for l in data["locations"]}
    chars_in = [c for c in sk.get("characters") or [] if isinstance(c, dict) and _s(c.get("name"))][:8]
    if len(chars_in) >= 2:
        n = len(chars_in)
        chars = []
        for i, c in enumerate(chars_in):
            role = _s(c.get("role"), "神秘人")
            loc_name = _s(c.get("location"))
            lid = by_name.get(loc_name) or next((v for k, v in by_name.items() if loc_name and (loc_name in k or k in loc_name)), None)
            rels = [{"target_id": "player", "type": "初识", "affinity": rng.randint(-10, 40)},
                    {"target_id": f"c_{(i + 1) % n + 1}", "type": rng.choice(["旧识", "同盟", "对手", "暗中提防"]),
                     "affinity": rng.randint(-50, 60)}]
            chars.append({"id": f"c_{i + 1}", "name": _s(c["name"])[:10], "role": role,
                          "persona": f"{role}，言行谨慎，心里藏着自己的打算", "goals": [f"守住作为{role}的秘密", "弄清眼前风波的真相"],
                          "relations": rels if n > 1 else rels[:1], "location_id": lid or f"loc_{i % len(data['locations']) + 1}",
                          "mood": rng.choice(["平静", "警惕", "焦虑", "好奇"]), "avatar_emoji": _s(c.get("emoji")) or None})
        data["characters"] = chars
    opts = [o if isinstance(o, str) else (o or {}).get("text") for o in sk.get("opening_options") or []]
    opts = [_s(o) for o in opts if _s(o)][:4]
    if opts:
        data["opening_options"] = [{"id": f"opt_{i + 1}", "text": o} for i, o in enumerate(opts)]
    first_loc = data["locations"][0]["name"] if data["locations"] else "此地"
    if req.mode != "education" or _s(sk.get("setting")):
        data["opening_scene"] = (f"{data['setting']}{data['initial_conflict']}此刻，你以{data['player']['role']}的身份"
                                 f"站在{first_loc}，故事从这里开始。")
    cards = [k for k in sk.get("knowledge_cards") or [] if isinstance(k, dict) and _s(k.get("title")) and _s(k.get("content"))]
    if cards:
        data["knowledge_cards"] = [{"id": f"k_{i + 1}", "title": _s(k["title"])[:30], "content": _s(k["content"]),
                                    "source": _s(k.get("source")) or None} for i, k in enumerate(cards[:8])]
    return data


async def _filter_world_text(world: World, req_minor: bool, rating: str) -> None:
    """入库文本一律使用 check_output 的 filtered_text（None 时回退原文）。"""
    for field in ("opening_scene", "setting", "initial_conflict", "premise"):
        orig = getattr(world, field)
        if orig:
            r = await guard.check_output(orig, minor_mode=req_minor, rating=rating)
            setattr(world, field, guard.SAFE_NOTICE if r.blocked and not r.filtered_text else (r.filtered_text or orig))
    for c in world.characters:
        if c.persona:
            r = await guard.check_output(c.persona, minor_mode=req_minor, rating=rating)
            c.persona = r.filtered_text or c.persona


async def generate_world_events(req: GenerateWorldRequest, world_id: str | None = None,
                                edu: dict[str, Any] | None = None) -> AsyncIterator[Event]:
    """两步世界生成（SSE 事件生成器）。

    1) 快速模型（qwen-flash 链）流式生成精简骨架 → 本地规则补齐为可玩世界 → 落库 → 推送 ``world``
       （``detail_status="enriching"``）→ ``done``（秒级预览）。
    2) 后台用 qwen-plus 链补全细节并合并（沿用骨架 id/名字）；完成后 ``detail_status="complete"``，失败则 ``"local"``
       （骨架世界仍可玩）。``wait_details=true`` 时 SSE 保持打开，补全后再推送一次 ``world`` 再 ``done``；
       否则前端轮询 ``GET /api/worlds/{id}`` 看 ``detail_status``。
    安全顺序（TEAM.md）：check_input(world_prompt/source_text) → 生成 → check_output → 持久化 filtered_text。
    """
    from app.graph.turn_graph import world_lock

    yield _prog("safety", "正在进行内容安全检查…", 5)
    text_in = "\n".join(x for x in [req.prompt, req.source_text or ""] if x)
    verdict = await guard.check_input(text_in, minor_mode=req.minor_mode, rating=req.rating,
                                      context="source_text" if req.mode == "education" else "world_prompt")
    if verdict.blocked:
        yield "safety", verdict.model_dump()
        yield "done", {"blocked": True, "world_id": None}
        return

    world_id = world_id or repo.new_id("w")
    data: dict[str, Any] | None = None
    skeleton: dict[str, Any] | None = None
    source = "fallback"
    if llm_enabled():
        yield _prog("outline", "造化中：勾勒世界骨架…", 15)
        holder: dict[str, Any] = {}
        msgs = prompts.skeleton_messages(req.prompt, req.genre, req.tone, req.length, req.minor_mode,
                                         req.source_text if req.mode == "education" else None)
        async for ev in _stream_skeleton(msgs, holder):
            yield ev
        skeleton = holder.get("data")
        if skeleton and skeleton.get("locations") and skeleton.get("characters"):
            data, source = skeleton_to_data(skeleton, req, edu), "llm"
        else:
            skeleton = None
            yield _prog("outline", "模型暂不可用，已切换本地兜底模板", 30)
    else:
        yield _prog("outline", "本地兜底模板：构思时代背景与基调…", 20)
    if data is None:
        data = (fallback.build_education_dict(req.source_text or req.prompt, (edu or {}).get("title"), (edu or {}).get("subject"))
                if req.mode == "education" else fallback.build_world_dict(req.prompt, req.genre, req.tone, req.length))
    yield _prog("locations", f"绘制地图：{len(data.get('locations') or [])} 个地点", 50)
    yield _prog("characters", f"唤醒角色：{len(data.get('characters') or [])} 位 NPC", 65)
    world = normalize_world(data, world_id=world_id, req=req, source=source)
    if req.mode == "education" and not world.knowledge_cards:
        fb = fallback.build_education_dict(req.source_text or req.prompt, (edu or {}).get("title"), (edu or {}).get("subject"))
        world.knowledge_cards = [KnowledgeCard(**k) for k in fb["knowledge_cards"]]
    yield _prog("conflict", "埋下初始冲突与伏笔", 75)

    out = await guard.check_output(json.dumps(world.model_dump(include={"title", "setting", "initial_conflict", "opening_scene"}),
                                              ensure_ascii=False), minor_mode=req.minor_mode, rating=req.rating)
    if out.blocked:
        log.warning("world output blocked, using fallback template")
        yield "safety", out.model_dump()
        world = normalize_world(fallback.build_world_dict("", None, None, req.length), world_id=world_id, req=req, source="fallback")
        source, skeleton = "fallback", None
    await _filter_world_text(world, req.minor_mode, req.rating)
    token = uuid.uuid4().hex[:10]
    world.state.flags["gen_request"] = req.model_dump(exclude={"wait_details"})
    world.state.flags["gen_token"] = token
    if edu:
        world.state.flags["edu"] = edu
    world.detail_status = "enriching" if skeleton else "complete"

    yield _prog("persist", "写入世界存档", 85)
    async with world_lock(world_id):
        existing = repo.load_world(world_id)
        if existing:  # regenerate in place: wipe old content (same id)
            world.created_at = existing.created_at
            repo.delete_world(world_id)
        repo.save_world(world)
        for c in world.npcs():  # 轨迹起点（上帝视角）
            repo.add_trajectory(world.id, c.id, 0, c.location_id, f"登场：{c.role}", c.mood)
    yield "world", world.model_dump(mode="json")
    yield _prog("memory", "构建世界记忆库", 95)
    await initial_memories(world)
    task = None
    if skeleton:
        task = asyncio.create_task(enrich_world(world_id, token, skeleton, req))
        _bg.add(task)
        task.add_done_callback(_bg.discard)
    if task is not None and req.wait_details:
        yield _prog("details", "精雕细琢：补全人物性格、关系与开场…", 97)
        try:
            full = await asyncio.wait_for(asyncio.shield(task), timeout=ENRICH_TIMEOUT)
        except asyncio.TimeoutError:
            full = None
        if full is not None:
            world = full
            yield "world", world.model_dump(mode="json")
    yield _prog("done", "世界已生成" if world.detail_status != "enriching" else "骨架已就绪，细节补全中…", 100)
    yield "done", {"world_id": world.id, "source": source, "detail_status": world.detail_status}


def _merge(world: World, d: dict[str, Any]) -> None:
    """把补全结果按名字/ID 合并进骨架世界：不改标题与名单（与预览一致）；已开始游玩则不覆盖开局相关状态。"""
    started = world.state.turn > 0
    for k in ("genre", "tone", "era", "setting", "initial_conflict"):
        if _s(d.get(k)):
            setattr(world, k, _s(d[k]))
    loc_by_name = {l.name: l for l in world.locations}
    rid_to_loc: dict[str, str] = {}
    for l in [x for x in d.get("locations") or [] if isinstance(x, dict)]:
        tgt = loc_by_name.get(_s(l.get("name"))) or world.loc(_s(l.get("id")))
        if not tgt:
            continue
        rid_to_loc[_s(l.get("id"), tgt.id)] = tgt.id
        if _s(l.get("description")):
            tgt.description = _s(l["description"])
        its = [str(i) for i in l.get("interactables") or [] if str(i).strip()][:6]
        if its:
            tgt.interactables = its
        for axis in ("x", "y"):
            try:
                v = float(l.get(axis))
                setattr(tgt, axis, max(0.0, min(100.0, v)))
            except (TypeError, ValueError):
                pass
    for l in [x for x in d.get("locations") or [] if isinstance(x, dict)]:
        tgt = loc_by_name.get(_s(l.get("name"))) or world.loc(_s(l.get("id")))
        conns = sorted({rid_to_loc[str(c)] for c in l.get("connections") or [] if str(c) in rid_to_loc} - {tgt.id}) if tgt else []
        if tgt and conns:
            tgt.connections = conns
    char_by_name = {c.name: c for c in world.npcs()}
    rid_to_char: dict[str, str] = {"player": "player", "玩家": "player"}
    chars_in = [x for x in d.get("characters") or [] if isinstance(x, dict)]
    for c in chars_in:
        tgt = char_by_name.get(_s(c.get("name"))) or (world.char(_s(c.get("id"))) if _s(c.get("id")) != "player" else None)
        if tgt:
            rid_to_char[_s(c.get("id"), tgt.id)] = tgt.id
            rid_to_char[tgt.name] = tgt.id
    for c in chars_in:
        tgt = char_by_name.get(_s(c.get("name"))) or (world.char(_s(c.get("id"))) if _s(c.get("id")) != "player" else None)
        if not tgt or tgt.is_player:
            continue
        if _s(c.get("persona")):
            tgt.persona = _s(c["persona"])
        goals = [str(g) for g in c.get("goals") or [] if str(g).strip()][:4]
        if goals:
            tgt.goals = goals
        rels = []
        for r in c.get("relations") or []:
            if isinstance(r, dict) and (tid := rid_to_char.get(_s(r.get("target_id")))) and tid != tgt.id:
                try:
                    aff = max(-100, min(100, int(r.get("affinity") or 0)))
                except (TypeError, ValueError):
                    aff = 0
                rels.append({"target_id": tid, "type": _s(r.get("type"), "相识"), "affinity": aff})
        if rels:
            from app.schemas import Relation
            tgt.relations = [Relation(**r) for r in rels]
        if _s(c.get("avatar_emoji")) and not tgt.avatar_emoji:
            tgt.avatar_emoji = _s(c["avatar_emoji"])
        if not started:
            lid = rid_to_loc.get(_s(c.get("location_id")))
            if lid:
                tgt.location_id = lid
            if _s(c.get("mood")):
                tgt.mood = _s(c["mood"])
    if not started:
        if _s(d.get("opening_scene")):
            world.opening_scene = _s(d["opening_scene"])
        opts = [o.get("text") if isinstance(o, dict) else o for o in d.get("opening_options") or []]
        opts = [_s(o) for o in opts if _s(o)][:4]
        if opts:
            world.opening_options = [Option(id=f"opt_{i + 1}", text=o) for i, o in enumerate(opts)]
        items = [it for it in d.get("items") or [] if isinstance(it, dict) and _s(it.get("name"))][:12]
        if items:
            world.items = [Item(id=f"it_{i + 1}", name=_s(it["name"]), description=_s(it.get("description")),
                                owner_id=rid_to_char.get(_s(it.get("owner_id")), "player" if not it.get("owner_id") else None))
                           for i, it in enumerate(items)]
        stats = {}
        for k, v in (d.get("stats") or {}).items():
            try:
                stats[str(k)] = max(0, min(100, int(v)))
            except (TypeError, ValueError):
                pass
        if stats:
            world.state.stats = stats
    cards = [k for k in d.get("knowledge_cards") or [] if isinstance(k, dict) and _s(k.get("title")) and _s(k.get("content"))]
    if world.mode == "education" and cards:
        have = {k.title for k in world.knowledge_cards}
        if not started:
            world.knowledge_cards = []
            have = set()
        for k in cards[:10]:
            if _s(k["title"]) not in have:
                world.knowledge_cards.append(KnowledgeCard(id=f"k_{len(world.knowledge_cards) + 1}", title=_s(k["title"])[:30],
                                                           content=_s(k["content"]), source=_s(k.get("source")) or None))


async def enrich_world(world_id: str, token: str, skeleton: dict[str, Any], req: GenerateWorldRequest) -> World | None:
    """第二步（后台）：qwen-plus 链补全细节。失败 → detail_status="local"（骨架世界已按本地规则补齐、可玩）。"""
    from app.graph.turn_graph import world_lock

    t0 = time.monotonic()
    w0 = repo.load_world(world_id)
    if not w0:
        return None
    sk = {"title": w0.title, "player": w0.player.model_dump(),
          "locations": [{"id": l.id, "name": l.name, "description": l.description} for l in w0.locations],
          "characters": [{"id": c.id, "name": c.name, "role": c.role, "location_id": c.location_id} for c in w0.npcs()],
          "setting": w0.setting, "initial_conflict": w0.initial_conflict}
    meta: dict[str, Any] = {}
    try:
        d = await chat_json(prompts.enrich_messages(sk, req.prompt or (req.source_text or "")[:200], req.minor_mode,
                                                    req.mode == "education"),
                            model=get_settings().chat_model, temperature=0.8 if req.mode == "story" else 0.4,
                            max_tokens=3500, meta=meta)
    except Exception:  # noqa: BLE001
        log.exception("enrich call crashed")
        d = None
    async with world_lock(world_id):
        w = repo.load_world(world_id)
        if not w or w.state.flags.get("gen_token") != token:
            return None  # 世界已删除或已被重新生成
        if d and (d.get("characters") or d.get("locations")):
            snapshot = w.model_copy(deep=True)
            try:
                _merge(w, d)
                await _filter_world_text(w, w.minor_mode, w.rating)
                w.detail_status = "complete"
            except Exception:  # noqa: BLE001
                log.exception("merge failed, keeping skeleton")
                w = snapshot
                w.detail_status = "local"
        else:
            w.detail_status = "local"
        w.state.flags["detail"] = {"model": meta.get("model"), "secs": round(time.monotonic() - t0, 1),
                                   "status": w.detail_status}
        repo.save_world(w)
        if w.detail_status == "complete":
            await _refresh_setting_memories(w)
    log.info("world %s details %s in %.1fs (model=%s)", world_id, w.detail_status, time.monotonic() - t0, meta.get("model"))
    return w


async def _refresh_setting_memories(world: World) -> None:
    """补全后刷新开局设定记忆（尚未开始游玩时整体替换；已开始则只追加人物设定）。"""
    if world.state.turn == 0:
        store.delete_from_turn(world.id, 0)
        await initial_memories(world)
    else:
        await store.add_memories(world.id, [{"content": f"{c.name}是{c.role}，{c.persona}；目标：{'、'.join(c.goals)}",
                                             "kind": "setting", "turn": 0, "chapter": 1, "refs": {"character_id": c.id}}
                                            for c in world.npcs()])
