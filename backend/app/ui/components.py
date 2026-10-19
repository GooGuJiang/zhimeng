"""F6 生成式 UI：依据当前剧情与世界数据生成界面组件规格（UIComponent，见 API.md）。

- props 严格来自世界数据（名字/数值/id 与世界一致，可交互 actions）。
- priority / layout 随剧情动态计算（例如刚发生高影响场外事件 → 事件流上移；体力低 → 状态面板突出；
  教育模式 → 知识卡占主区）。
- openui：可选的 OpenUI Lang 1.0 程序（frontend/openui/system-prompt.txt 的组件库），由模板确定性生成，
  首行固定 ``root = Col(...)``；前端解析失败时会退回用 props 自行渲染。
"""
from __future__ import annotations

import json
from typing import Any

from app.schemas import AI_LABEL, Option, World, WorldEvent

ALL_TYPES = ["status_panel", "relationship_graph", "inventory", "map", "event_feed", "knowledge_cards", "choice_list"]
IDS = {"status_panel": "status", "relationship_graph": "relations", "inventory": "inventory", "map": "map",
       "event_feed": "events", "knowledge_cards": "knowledge", "choice_list": "choices"}


# ------------------------------------------------------------------ OpenUI Lang 序列化
def _v(x: Any) -> str:
    """Python 值 → OpenUI Lang 字面量（对象键不加引号）。"""
    if isinstance(x, bool):
        return "true" if x else "false"
    if x is None:
        return "null"
    if isinstance(x, (int, float)):
        return str(round(x, 2)) if isinstance(x, float) else str(x)
    if isinstance(x, str):
        return json.dumps(x, ensure_ascii=False)
    if isinstance(x, (list, tuple)):
        return "[" + ", ".join(_v(i) for i in x) + "]"
    if isinstance(x, dict):
        return "{" + ", ".join(f"{k}: {_v(v)}" for k, v in x.items() if v is not None) + "}"
    return json.dumps(str(x), ensure_ascii=False)


def _program(root_children: list[str], defs: list[tuple[str, str]]) -> str:
    lines = [f"root = Col([{', '.join(root_children)}])"] + [f"{n} = {e}" for n, e in defs]
    return "\n".join(lines)


def _act(text: str) -> str:
    return f"@Act({_v(text)})"


# ------------------------------------------------------------------ 各组件
def _player(world: World):
    return world.char("player")


def status_panel(world: World) -> dict[str, Any]:
    st = world.state
    loc = world.loc(st.player_location_id)
    p = _player(world)
    tags = [world.genre, {"all": "全年龄", "teen": "12+", "mature": "16+"}.get(world.rating, world.rating)]
    if world.minor_mode:
        tags.append("未成年人模式")
    if world.mode == "education":
        tags.append("教育模式")
    props = {"player": {"name": world.player.name, "role": world.player.role, "location": loc.name if loc else "未知",
                        "hp": st.hp, "mood": p.mood if p else "平静"},
             "stats": dict(st.stats), "time": st.time, "chapter": st.chapter, "turn": st.turn, "tags": [t for t in tags if t]}
    actions = [{"id": "look", "label": "环顾四周", "kind": "turn", "payload": {"action": f"仔细观察{loc.name if loc else '周围'}"}},
               {"id": "recall", "label": "回忆线索", "kind": "query", "payload": {"question": "到目前为止我掌握了哪些关键线索？"}}]
    tone = "danger" if st.hp < 40 else "gold"
    meters = [(f"m{i}", f"Meter({_v(k)}, {int(v)}, 100, {_v('azure')})") for i, (k, v) in enumerate(list(st.stats.items())[:4])]
    defs = [("panel", f"Panel([head, hp{''.join(', ' + n for n, _ in meters)}, btns], {_v(world.player.name + '的状态')}, {_v(tone)})"),
            ("head", f"Row([Stat(\"所在\", {_v(props['player']['location'])}), Stat(\"时辰\", {_v(st.time)}), "
                     f"Stat(\"进度\", {_v(f'第{st.chapter}章·第{st.turn}回合')})], 2, \"between\")"),
            ("hp", f"Meter(\"体力\", {st.hp}, 100, {_v('danger' if st.hp < 40 else 'rose')})"), *meters,
            ("btns", f"Row([Button(\"环顾四周\", {_act(actions[0]['payload']['action'])}, \"ghost\"), "
                     f"Button(\"回忆线索\", @Ask({_v(actions[1]['payload']['question'])}), \"ghost\")])")]
    return _comp(world, "status_panel", "角色状态", props, actions, _program(["panel"], defs))


def relationship_graph(world: World) -> dict[str, Any]:
    nodes = [{"id": c.id, "label": c.name, "role": c.role, "mood": c.mood, "is_player": c.is_player,
              "emoji": c.avatar_emoji or ("🧭" if c.is_player else "👤")} for c in world.characters]
    ids = {c.id for c in world.characters}
    edges, seen = [], set()
    for c in world.characters:
        for r in c.relations:
            if r.target_id in ids and (c.id, r.target_id) not in seen:
                seen.add((c.id, r.target_id))
                edges.append({"source": c.id, "target": r.target_id, "type": r.type, "affinity": r.affinity})
    here = [c for c in world.npcs() if c.location_id == world.state.player_location_id]
    actions = [{"id": f"talk_{c.id}", "label": f"与{c.name}交谈", "kind": "turn", "payload": {"action": f"和{c.name}交谈"}}
               for c in (here or world.npcs())[:3]]
    btns = ", ".join(f"Button({_v(a['label'])}, {_act(a['payload']['action'])}, \"ghost\")" for a in actions)
    defs = [("panel", f"Panel([g, btns], \"人物关系\", \"rose\")"), ("g", f"RelationGraph({_v(nodes)}, {_v(edges)})"),
            ("btns", f"Row([{btns}])")]
    return _comp(world, "relationship_graph", "人物关系", {"nodes": nodes, "edges": edges}, actions, _program(["panel"], defs))


def inventory(world: World) -> dict[str, Any]:
    items = [{"id": i.id, "name": i.name, "description": i.description, "quantity": i.quantity}
             for i in world.items if i.owner_id == "player"]
    actions = [{"id": f"use_{i['id']}", "label": f"查看{i['name']}", "kind": "turn", "payload": {"action": f"仔细查看{i['name']}"}}
               for i in items[:3]]
    defs = [("panel", "Panel([inv], \"随身物品\", \"jade\")"),
            ("inv", f"Inventory({_v(items)})")]
    return _comp(world, "inventory", "随身物品", {"items": items}, actions, _program(["panel"], defs))


def world_map(world: World) -> dict[str, Any]:
    locs = [{"id": l.id, "name": l.name, "x": l.x, "y": l.y, "description": l.description,
             "characters": [c.name for c in world.npcs() if c.location_id == l.id]} for l in world.locations]
    edges, seen = [], set()
    for l in world.locations:
        for t in l.connections:
            k = tuple(sorted((l.id, t)))
            if k not in seen:
                seen.add(k)
                edges.append({"source": k[0], "target": k[1]})
    cur = world.loc(world.state.player_location_id)
    nxt = [world.loc(t) for t in (cur.connections if cur else [])]
    actions = [{"id": f"go_{l.id}", "label": f"前往{l.name}", "kind": "navigate",
                "payload": {"location_id": l.id, "action": f"前往{l.name}"}} for l in nxt if l][:4]
    defs = [("panel", "Panel([m], \"世界地图\", \"azure\")"),
            ("m", f"WorldMap({_v(locs)}, {_v(edges)}, {_v(world.state.player_location_id)})")]
    return _comp(world, "map", "世界地图", {"locations": locs, "edges": edges,
                                            "current_location_id": world.state.player_location_id}, actions,
                 _program(["panel"], defs))


def event_feed(world: World, events: list[WorldEvent]) -> dict[str, Any]:
    evs = events[:8]
    names = {c.id: c.name for c in world.characters}
    actions = []
    for e in evs[:2]:
        who = "、".join(names.get(a, a) for a in e.actor_ids[:2])
        actions.append({"id": f"probe_{e.id}", "label": "追查此事", "kind": "turn",
                        "payload": {"action": f"打听{who + '的' if who else ''}动向：{e.summary[:20]}"}})
    lines = [(f"e{i}", f"EventLine({_v(e.summary)}, {_v(e.in_world_time)}, {_v(e.type)}, {_v(e.impact)})") for i, e in enumerate(evs)]
    btn = [("b0", f"Button(\"追查此事\", {_act(actions[0]['payload']['action'])}, \"ghost\")")] if actions else []
    children = ", ".join([n for n, _ in lines] + [n for n, _ in btn]) or "empty"
    defs = [("panel", f"Panel([{children}], \"场外大事件\", \"muted\")"), *lines, *btn]
    if not lines and not btn:
        defs.append(("empty", "Text(\"暂时风平浪静……\", \"muted\", \"sm\")"))
    return _comp(world, "event_feed", "场外大事件", {"events": [e.model_dump() for e in evs]}, actions, _program(["panel"], defs))


def knowledge_cards(world: World) -> dict[str, Any]:
    cards = world.knowledge_cards
    actions = [{"id": f"ask_{k.id}", "label": f"请教：{k.title[:8]}", "kind": "query",
                "payload": {"question": f"关于“{k.title}”，原文是怎么说的？"}} for k in cards[:2]]
    defs = [("panel", f"Panel([grid], \"知识卡\", \"gold\")"),
            ("grid", f"Grid([{', '.join(f'k{i}' for i in range(len(cards[:8])))}], 2)"),
            *[(f"k{i}", f"KnowledgeCard({_v(k.title)}, {_v(k.content)}, {_v(k.source or '')})") for i, k in enumerate(cards[:8])]]
    return _comp(world, "knowledge_cards", "知识卡", {"cards": [k.model_dump() for k in cards]}, actions, _program(["panel"], defs))


def choice_list(world: World, options: list[Option]) -> dict[str, Any]:
    opts = [o.model_dump(exclude_none=True) for o in options]
    actions = [{"id": o["id"], "label": o["text"], "kind": "turn", "payload": {"action": o["text"], "option_id": o["id"]}}
               for o in opts]
    defs = [("panel", "Panel([c], \"下一步\", \"ink\")"), ("c", f"Choices({_v(opts)})")]
    return _comp(world, "choice_list", "下一步", {"options": opts}, actions, _program(["panel"], defs))


LAYOUT = {"status_panel": ("side", "md"), "relationship_graph": ("side", "md"), "inventory": ("side", "sm"),
          "map": ("side", "md"), "event_feed": ("bottom", "md"), "knowledge_cards": ("main", "md"),
          "choice_list": ("bottom", "sm")}


def _comp(world: World, type_: str, title: str, props: dict[str, Any], actions: list[dict[str, Any]],
          openui: str) -> dict[str, Any]:
    area, size = LAYOUT[type_]
    return {"id": IDS[type_], "type": type_, "title": title, "priority": 50, "layout": {"area": area, "size": size},
            "props": props, "actions": actions, "openui": openui, "ai_generated": True, "ai_label": AI_LABEL}


def _prioritize(world: World, comps: list[dict[str, Any]], events: list[WorldEvent], focus: str | None,
                moved: bool) -> None:
    """根据剧情动态决定组件的显著程度与布局。"""
    st = world.state
    unseen_high = [e for e in events[:5] if not e.seen and e.impact in ("medium", "high")]
    for c in comps:
        t, p = c["type"], 50
        if t == "status_panel":
            p = 90 if st.hp < 40 else 70
            if st.hp < 40:
                c["layout"] = {"area": "main", "size": "md"}
        elif t == "relationship_graph":
            p = 60 + min(20, len([n for n in world.npcs() if n.location_id == st.player_location_id]) * 10)
        elif t == "map":
            p = 75 if moved else 55
        elif t == "event_feed":
            p = 85 if unseen_high else 40
            if unseen_high:
                c["layout"] = {"area": "main", "size": "md"}
        elif t == "inventory":
            p = 45 + min(20, len(c["props"]["items"]) * 3)
        elif t == "knowledge_cards":
            p = 88 if world.mode == "education" else 20
            if world.mode == "education":
                c["layout"] = {"area": "main", "size": "lg"}
        elif t == "choice_list":
            p = 65
        if focus and focus in (t, c["id"]):
            p = 100
        c["priority"] = p


def build_components(world: World, *, events: list[WorldEvent] | None = None, options: list[Option] | None = None,
                     types: list[str] | None = None, focus: str | None = None, moved: bool = False) -> list[dict[str, Any]]:
    events = events or []
    wanted = [t for t in (types or ALL_TYPES) if t in ALL_TYPES]
    if not types and world.mode != "education":
        wanted = [t for t in wanted if t != "knowledge_cards"]
    builders = {"status_panel": lambda: status_panel(world), "relationship_graph": lambda: relationship_graph(world),
                "inventory": lambda: inventory(world), "map": lambda: world_map(world),
                "event_feed": lambda: event_feed(world, events), "knowledge_cards": lambda: knowledge_cards(world),
                "choice_list": lambda: choice_list(world, options or world.opening_options)}
    comps = [builders[t]() for t in wanted]
    _prioritize(world, comps, events, focus, moved)
    comps.sort(key=lambda c: -c["priority"])
    return comps
