"""Layered prompt engineering: [system safety] + [world setting] + [character persona] + [narrative style]."""
from __future__ import annotations

import json

from app.schemas import Character, World

SAFETY_LAYER = (
    "你是《织梦》互动叙事引擎的一部分。遵守中国法律法规与公序良俗：不输出色情、极端暴力、违法犯罪教程、"
    "歧视或政治敏感内容；如用户表现出自伤倾向，温和地引导其寻求帮助。所有内容都是虚构的AI生成内容。"
)

WORLD_SCHEMA = """{
 "title": "世界标题(≤12字)", "genre": "题材", "tone": "叙事基调", "era": "时代背景", "setting": "世界概述(80-150字)",
 "premise": "一句话核心设定", "initial_conflict": "初始冲突(50-100字)",
 "player": {"name": "玩家角色名", "role": "玩家身份"},
 "locations": [{"id": "loc_1", "name": "地点名", "description": "描述", "x": 0-100, "y": 0-100,
                "connections": ["loc_2"], "interactables": ["可交互物"]}],
 "characters": [{"id": "c_1", "name": "姓名", "role": "身份", "persona": "性格与说话风格", "goals": ["目标"],
                 "relations": [{"target_id": "c_2 或 player", "type": "关系", "affinity": -100到100}],
                 "location_id": "loc_1", "mood": "情绪", "avatar_emoji": "一个emoji"}],
 "items": [{"id": "it_1", "name": "物品", "description": "描述", "owner_id": "player 或角色id 或 null"}],
 "stats": {"属性名": 0-100},
 "opening_scene": "开场场景叙事(150-300字，第二人称)",
 "opening_options": [{"id": "opt_1", "text": "选项"}]
}"""


def world_messages(prompt: str, genre: str | None, tone: str | None, length: str, language: str,
                   minor_mode: bool) -> list[dict[str, str]]:
    n_loc, n_char = {"short": (4, 3), "medium": (5, 4), "long": (7, 6)}[length]
    sys = (SAFETY_LAYER + "\n你是“造化”世界架构师。根据用户的一句话生成一个可游玩的互动叙事世界，严格输出 JSON，结构如下：\n"
           + WORLD_SCHEMA + f"\n要求：{n_loc} 个地点、{n_char} 个NPC（不含玩家），NPC之间及与玩家(player)要有关系网；"
           "地点坐标分散；初始冲突要能驱动剧情；3个开场选项。")
    if minor_mode:
        sys += "\n未成年人模式：内容适合全年龄，避免恐怖血腥与恋爱描写。"
    user = f"主题：{prompt}\n题材：{genre or '自动'}\n基调：{tone or '自动'}\n语言：{language}"
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def education_messages(source_text: str, title: str | None, subject: str | None, grade: str | None) -> list[dict[str, str]]:
    sys = (SAFETY_LAYER + "\n你是“文化/教育模式”的世界架构师。把下面的课文/史料转化为学生可以“走进”的互动世界。"
           "必须忠于原文与史实，不得编造与原文矛盾的史实；虚构的只能是玩家视角与细节，并在知识卡中只写准确知识。"
           "严格输出 JSON，结构如下：\n" + WORLD_SCHEMA[:-1] +
           ',\n "knowledge_cards": [{"id": "k_1", "title": "知识点", "content": "准确的解释(40-120字)", "source": "原文引文或出处"}]\n}'
           "\n要求：4-5 个地点、3-4 个NPC（优先原文中的真实人物），5-8 张知识卡，内容适合中小学生。")
    user = f"标题：{title or '自动'}\n学科：{subject or '自动'}\n年级：{grade or '通用'}\n原文：\n{source_text[:6000]}"
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def world_brief(world: World) -> str:
    locs = "；".join(f"{l.name}({l.id})" for l in world.locations)
    chars = "；".join(f"{c.name}({c.id},{c.role},在{(world.loc(c.location_id).name if world.loc(c.location_id) else '未知')},情绪{c.mood})"
                     for c in world.npcs())
    return (f"【世界】{world.title}｜{world.genre}｜基调：{world.tone}｜时代：{world.era}\n{world.setting}\n"
            f"【核心冲突】{world.initial_conflict}\n【地点】{locs}\n【NPC】{chars}\n"
            f"【玩家】{world.player.name}（{world.player.role}），当前位置：{(world.loc(world.state.player_location_id).name if world.loc(world.state.player_location_id) else '未知')}"
            f"，时间：{world.state.time}，第{world.state.chapter}章第{world.state.turn}回合")


def persona_layer(c: Character) -> str:
    return f"【角色】{c.name}，{c.role}。性格：{c.persona}。目标：{'、'.join(c.goals)}。当前情绪：{c.mood}。"


STYLE_LAYER = ("【叙事风格】第二人称“你”，沉浸式、有画面感，200-350字；对白用中文引号；结尾留悬念，"
               "不要替玩家做重大决定；不要输出选项列表或JSON。")


def director_messages(world: World, action: str, memory_ctx: str, recent: str, npc_ctx: str,
                      events_ctx: str, inject_ctx: str, minor_mode: bool) -> list[dict[str, str]]:
    sys = "\n".join([SAFETY_LAYER, "你是导演Agent，负责编排叙事节奏，把场外事件和上帝视角插入的事件自然编织进主线，并保持与世界记忆一致。",
                     world_brief(world), STYLE_LAYER])
    if world.mode == "education":
        sys += "\n【教育模式】叙事须符合史实/原文，可在叙事中自然带出知识点。"
    if minor_mode:
        sys += "\n【未成年人模式】内容适合全年龄。"
    user = (f"【相关世界记忆（必须保持一致，不得矛盾）】\n{memory_ctx or '无'}\n\n【最近剧情】\n{recent or '（开局）'}\n\n"
            f"【焦点NPC意图】\n{npc_ctx or '无'}\n\n【新近场外事件】\n{events_ctx or '无'}\n\n"
            f"【上帝视角插入事件（必须在本回合体现）】\n{inject_ctx or '无'}\n\n【玩家行动】{action}\n\n请续写本回合叙事。")
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def extract_messages(world: World, action: str, narration: str) -> list[dict[str, str]]:
    ids = {"locations": [l.id for l in world.locations], "characters": [c.id for c in world.characters],
           "items": [i.id for i in world.items]}
    schema = """{
 "facts": ["本回合新确立的、以后需要记住的客观事实(人名/物品/线索/承诺/地点变化)，每条≤40字，2-5条"],
 "options": [{"id": "opt_1", "text": "下一步可选行动(≤20字)"}],
 "player_location_id": "地点id或null(不变)",
 "hp_delta": 0, "stats_delta": {"属性": 整数},
 "items_gained": [{"name": "物品", "description": "描述"}], "items_lost": ["物品名"],
 "character_updates": [{"id": "角色id", "mood": "新情绪", "location_id": "地点id或null", "affinity_delta": 整数}],
 "key_scene": false, "scene_prompt": "若key_scene为true，给出一句插画描述(画面/光线/构图)",
 "knowledge_cards": [{"title": "知识点", "content": "解释", "source": "出处"}],
 "ending": null
}"""
    sys = ("你是事实抽取器。根据本回合叙事抽取结构化信息，严格输出 JSON：\n" + schema +
           f"\n可用id：{json.dumps(ids, ensure_ascii=False)}\n3个选项；key_scene 仅在剧情重大转折时为 true；"
           + ("knowledge_cards 给出0-2个与本回合相关的准确知识点；" if world.mode == "education" else "knowledge_cards 为空数组；")
           + "ending 仅在故事明确结局时填写一句结局描述。")
    return [{"role": "system", "content": sys},
            {"role": "user", "content": f"世界：{world.title}\n玩家行动：{action}\n叙事：\n{narration}"}]


def npc_focus_messages(world: World, c: Character, action: str, memories: str) -> list[dict[str, str]]:
    sys = (SAFETY_LAYER + "\n你是角色Agent，扮演下述角色，根据自身目标与记忆决定本回合对玩家行动的反应。" + persona_layer(c) +
           '\n严格输出 JSON：{"intent": "本回合意图(≤40字)", "action": "具体行动(≤60字)", "line": "一句台词", '
           '"mood": "情绪", "affinity_delta": -10到10}')
    return [{"role": "system", "content": sys},
            {"role": "user", "content": f"{world_brief(world)}\n你的记忆：{memories or '无'}\n玩家行动：{action}"}]


def npc_batch_messages(world: World, chars: list[Character], recent: str) -> list[dict[str, str]]:
    roster = "\n".join(persona_layer(c) + f"位置：{c.location_id}" for c in chars)
    sys = (SAFETY_LAYER + "\n你同时驱动多个不在玩家身边的角色Agent，让他们按各自目标自主行动，产生“场外事件”。"
           '严格输出 JSON：{"actions": [{"id": "角色id", "action": "该角色在场外做了什么(≤60字)", '
           '"location_id": "行动后所在地点id", "mood": "情绪", "impact": "low|medium|high"}]}')
    return [{"role": "system", "content": sys},
            {"role": "user", "content": f"{world_brief(world)}\n地点id：{[l.id for l in world.locations]}\n角色：\n{roster}\n最近剧情：{recent}"}]


def world_agent_messages(world: World, recent: str) -> list[dict[str, str]]:
    sys = (SAFETY_LAYER + "\n你是世界Agent，负责推进时间线与全局事件(天气、社会动向、势力变化)。"
           '严格输出 JSON：{"time": "新的世界时间标签，如 第2天·黄昏", "event": "一句全局事件，或空字符串", "impact": "low|medium|high"}')
    return [{"role": "system", "content": sys},
            {"role": "user", "content": f"{world_brief(world)}\n最近剧情：{recent}"}]


def summary_messages(world: World, chapter: int, text: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": "你是记忆压缩器。把一章剧情压缩成 120 字以内的摘要，保留人名、物品、线索、因果，客观陈述。只输出摘要文本。"},
            {"role": "user", "content": f"世界：{world.title} 第{chapter}章\n{text[:6000]}"}]


def memory_answer_messages(world: World, question: str, cites: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": "你是世界记忆管理员。只能依据给定的记忆条目回答玩家关于过往剧情的提问，"
                                          "在句中用[编号]标注出处；没有依据时如实说不记得。回答≤120字。"},
            {"role": "user", "content": f"世界：{world.title}\n记忆条目：\n{cites}\n问题：{question}"}]


def education_summary_messages(world: World, timeline: str) -> list[dict[str, str]]:
    cards = "\n".join(f"- {k.title}：{k.content}" for k in world.knowledge_cards)
    return [{"role": "system", "content": "你是教学助手，为学生生成课后学习小结。严格输出 JSON："
                                          '{"key_points": ["要点"], "quiz": [{"question": "题目", "options": ["A","B","C","D"], '
                                          '"answer_index": 0, "explanation": "解析"}], "reflection": "一段思考引导(≤80字)"}'
                                          "；3-5个要点，3道选择题，严格基于知识卡，保证准确。"},
            {"role": "user", "content": f"主题：{world.title}\n知识卡：\n{cards}\n学习历程：\n{timeline}"}]


# ---------------------------------------------------------------- 两步世界生成
SKELETON_SCHEMA = """{"title":"≤10字","genre":"题材","tone":"基调≤12字","era":"时代≤15字","setting":"世界概述≤60字",
"initial_conflict":"初始冲突≤50字","player":{"name":"玩家名","role":"身份"},
"locations":[{"name":"地点名","description":"≤15字"}],
"characters":[{"name":"姓名","role":"身份","location":"所在地点名","emoji":"一个emoji"}],
"opening_options":["开场选项≤12字"]}"""


def skeleton_messages(prompt: str, genre: str | None, tone: str | None, length: str, minor_mode: bool,
                      source_text: str | None = None) -> list[dict[str, str]]:
    """第一步：精简骨架（快速模型，几百 token 内，保证秒级预览）。"""
    n_loc, n_char = {"short": (4, 3), "medium": (5, 4), "long": (6, 5)}[length]
    sys = (SAFETY_LAYER + "\n你是“造化”世界架构师。快速勾勒一个可游玩的互动叙事世界骨架，只输出紧凑 JSON（不要换行缩进）：\n"
           + SKELETON_SCHEMA + f"\n要求：{n_loc}个地点，{n_char}个NPC（不含玩家），3个开场选项，字段尽量短。")
    if source_text:
        sys += ('\n这是文化/教育模式：世界必须忠于原文与史实，NPC优先原文人物；额外输出 "knowledge_cards":'
                '[{"title":"知识点","content":"准确解释≤60字","source":"原文引文"}]（4-6张）。')
    if minor_mode:
        sys += "\n未成年人模式：内容适合全年龄。"
    user = f"主题：{prompt or '根据原文'}\n题材：{genre or '自动'}\n基调：{tone or '自动'}"
    if source_text:
        user += f"\n原文：\n{source_text[:3000]}"
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def enrich_messages(skeleton: dict, prompt: str, minor_mode: bool, education: bool) -> list[dict[str, str]]:
    """第二步：在骨架基础上补全细节；必须沿用骨架的 id 与名字（前端已展示预览）。"""
    sys = (SAFETY_LAYER + "\n你是“造化”世界架构师。下面是已经展示给玩家的世界骨架（含 id），请在不改变标题、地点名、角色名与 id 的前提下补全细节，"
           "严格输出 JSON，结构如下：\n" + WORLD_SCHEMA[:-1] +
           (',\n "knowledge_cards": [{"id": "k_1", "title": "知识点", "content": "准确解释", "source": "出处"}]\n}' if education else "\n}") +
           "\n要求：locations/characters 的 id 与骨架一致；为每个角色写性格(persona)、2个目标、与玩家(player)及其他角色的关系；"
           "地点给出描述、坐标(0-100，分散)、相邻地点 connections 与 2-3 个可交互物；3-4 件物品；2-4 项属性 stats；"
           "开场场景 150-250 字第二人称；3 个开场选项。" + ("\n教育模式：忠于原文史实，知识卡 5-8 张。" if education else ""))
    if minor_mode:
        sys += "\n未成年人模式：内容适合全年龄。"
    return [{"role": "system", "content": sys},
            {"role": "user", "content": f"主题：{prompt}\n骨架：{json.dumps(skeleton, ensure_ascii=False)}"}]
