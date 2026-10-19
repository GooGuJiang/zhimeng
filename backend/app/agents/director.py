"""导演 Agent：叙事流式生成 + 事实抽取 + 章节摘要压缩（F2/F4），以及记忆问答、教育小结（F4/F10）。"""
from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from app.agents import fallback, prompts
from app.config import get_settings
from app.llm.client import LLMUnavailable, chat_json, chat_stream_resumable, chat_text, llm_enabled
from app.schemas import Citation, World

log = logging.getLogger("zhimeng.director")


def _chunks(text: str, size: int = 3) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


async def narrate_stream(world: World, action: str, *, memory_ctx: str, recent: str, npc_ctx: str,
                         events_ctx: str, inject_ctx: str, focus: Any, event_lines: list[str],
                         injects: list[str], turn: int) -> AsyncIterator[tuple[str, str]]:
    """产出 (source, chunk)。LLM 流在首字前失败 → 本地模板；首字后失败 → 抛 LLMUnavailable（回合不提交，可重试）。"""
    if llm_enabled():
        msgs = prompts.director_messages(world, action, memory_ctx, recent, npc_ctx, events_ctx, inject_ctx,
                                         world.minor_mode)
        got = False
        try:  # 首字后断流：带已输出部分续写（chat_stream_resumable），续写用尽才放弃本回合（不提交、可重试）
            async for chunk in chat_stream_resumable(msgs, temperature=0.85, max_tokens=900):
                got = True
                yield "llm", chunk
            if got:
                return
        except LLMUnavailable:
            if got:
                raise
            log.warning("director stream failed before first token → fallback narration")
    text = fallback.narrate(world, action, focus, event_lines, injects, turn)
    for c in _chunks(text):
        yield "fallback", c


_GIVE_RE = re.compile(r"(?:给了我|交给我|递给我|得到了?|拿到了?|捡到了?|发现了?)(?:一|两|几)?(?:枚|个|张|把|封|本|块|件|只|颗|串|份)?([^，,。！!？?；;]{1,14})")


def fallback_extract(world: World, action: str, narration: str, focus: Any) -> dict[str, Any]:
    """确定性事实抽取：地点移动、获得物品、关键事实。"""
    facts = [f"你{fallback.second_person(action)}"]
    loc_id = fallback.detect_location(world, action)
    gained = []
    m = _GIVE_RE.search(action)
    if m:
        name = re.sub(r"^(?:一|两|几)?(?:枚|个|张|把|封|本|块|件|只|颗|串|份)", "", m.group(1)).strip()
        name = re.sub(r"^刻着[^的]{1,6}的", "", name) or name
        if name:
            gained.append({"name": name[:10], "description": f"第{world.state.turn + 1}回合获得：{m.group(0)[:30]}"})
            facts.append(f"你获得了{m.group(1).replace('我', '你')}")
    if loc_id and loc_id != world.state.player_location_id:
        facts.append(f"你来到了{world.loc(loc_id).name}")  # type: ignore[union-attr]
    if focus is not None:
        facts.append(f"{focus.name}与你有过一番交谈")
    rng = fallback.seed_rng(world.id, world.state.turn, action, "x")
    stat_keys = list(world.state.stats)
    return {"facts": facts[:5], "player_location_id": loc_id, "hp_delta": rng.choice([0, 0, -2, 1]),
            "stats_delta": {stat_keys[rng.randrange(len(stat_keys))]: rng.randint(1, 3)} if stat_keys else {},
            "items_gained": gained, "items_lost": [], "character_updates": [], "options": [],
            "key_scene": False, "scene_prompt": "", "knowledge_cards": [], "ending": None, "source": "fallback"}


async def extract(world: World, action: str, narration: str, focus: Any) -> dict[str, Any]:
    if llm_enabled():
        d = await chat_json(prompts.extract_messages(world, action, narration), model=get_settings().fast_model,
                            temperature=0.2, max_tokens=900)
        if d:
            base = fallback_extract(world, action, narration, focus)
            for k in base:
                if d.get(k) not in (None, "", [], {}):
                    base[k] = d[k]
            base["facts"] = [str(f)[:80] for f in (d.get("facts") or base["facts"]) if str(f).strip()][:6]
            base["source"] = "llm"
            return base
    return fallback_extract(world, action, narration, focus)


async def chapter_summary(world: World, chapter: int, turns: list[Any]) -> str:
    text = "\n".join(f"[第{t.index}回合] 行动：{t.action}\n{t.narration}" for t in turns)
    if llm_enabled():
        out = await chat_text(prompts.summary_messages(world, chapter, text), model=get_settings().fast_model,
                              temperature=0.3, max_tokens=300)
        if out and out.strip():
            return out.strip()[:400]
    acts = "；".join(fallback.second_person(t.action) for t in turns)
    facts = "；".join(f for t in turns for f in (t.facts or [])[1:2])
    return f"第{chapter}章（第{turns[0].index}-{turns[-1].index}回合）：你{acts}。" + (f"要点：{facts}。" if facts else "")


async def answer_question(world: World, question: str, cites: list[Citation]) -> str:
    if not cites:
        return "世界记忆中没有找到与此相关的记录，也许这件事还没有发生过。"
    numbered = "\n".join(f"[{i + 1}]（{c.source}）{c.content}" for i, c in enumerate(cites))
    if llm_enabled():
        out = await chat_text(prompts.memory_answer_messages(world, question, numbered),
                              model=get_settings().fast_model, temperature=0.2, max_tokens=300)
        if out and out.strip():
            return out.strip()
    top = cites[:2]
    body = "；".join(f"{c.content[:70]}{'…' if len(c.content) > 70 else ''}[{i + 1}]" for i, c in enumerate(top))
    return f"根据世界记忆：{body}。（出处：{'、'.join(c.source for c in top)}）"


async def education_summary(world: World, timeline: list[dict[str, Any]]) -> dict[str, Any]:
    cards = world.knowledge_cards
    if llm_enabled() and cards:
        tl = "\n".join(f"第{t['turn']}回合：{t['summary']}" for t in timeline)
        d = await chat_json(prompts.education_summary_messages(world, tl), temperature=0.3, max_tokens=1500)
        quiz = []
        for q in (d or {}).get("quiz") or []:
            try:
                opts = [str(o) for o in q["options"]][:4]
                ai = int(q.get("answer_index", 0))
                if len(opts) >= 2 and 0 <= ai < len(opts):
                    quiz.append({"question": str(q["question"]), "options": opts, "answer_index": ai,
                                 "explanation": str(q.get("explanation") or "")})
            except (KeyError, TypeError, ValueError):
                continue
        if d and d.get("key_points") and quiz:
            return {"key_points": [str(k) for k in d["key_points"]][:6], "quiz": quiz,
                    "reflection": str(d.get("reflection") or ""), "source": "llm"}
    # 兜底：严格基于知识卡出题（不编造知识）
    key_points = [f"{k.title.split('：')[0]}：{k.content}" for k in cards][:5] or [world.premise]
    quiz = []
    for i, k in enumerate(cards[:3]):
        rng = fallback.seed_rng(world.id, k.id, "quiz")
        others = [c.content[:40] for c in cards if c.id != k.id]
        rng.shuffle(others)
        opts = [k.content[:40]] + others[:3]
        if len(opts) < 2:
            opts.append("以上都不是原文内容")
        order = list(range(len(opts)))
        rng.shuffle(order)
        shuffled = [opts[j] for j in order]
        quiz.append({"question": f"下列哪一项是“{k.title.split('：')[0]}”对应的原文/知识内容？", "options": shuffled,
                     "answer_index": order.index(0), "explanation": f"出处：{k.source or '原文'}。{k.content}"})
    if not quiz:
        quiz = [{"question": f"本次学习的主题是什么？", "options": [world.title, "其他内容"], "answer_index": 0,
                 "explanation": world.premise}]
    return {"key_points": key_points, "quiz": quiz,
            "reflection": f"回顾你在《{world.title}》中的探索：哪一个细节最打动你？它和今天的生活有什么联系？",
            "source": "fallback"}
