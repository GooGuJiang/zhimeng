"""F4 世界记忆：列表 / 带出处的记忆问答 / 章节摘要。"""
from __future__ import annotations

import re

from fastapi import APIRouter, Query

from app.agents import director
from app.memory import store
from app.routes.deps import world_or_404
from app.schemas import AI_LABEL, Citation, MemoryAnswer, MemoryItem, MemoryQuery
from app.services import guard, repo

router = APIRouter(tags=["memory"])
_CN = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _num(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    if s in _CN:
        return _CN[s]
    if len(s) == 2 and s[0] == "十":
        return 10 + _CN.get(s[1], 0)
    if len(s) == 2 and s[1] == "十":
        return _CN.get(s[0], 0) * 10
    return None


def target_chapter(question: str, current: int) -> int | None:
    """解析“第一章”“三章前”“上一章”“开头”等时间指代。"""
    if m := re.search(r"([0-9一二两三四五六七八九十]{1,3})章(?:之)?前", question):
        n = _num(m.group(1))
        return max(1, current - n) if n else None
    if m := re.search(r"第([0-9一二两三四五六七八九十]{1,3})章", question):
        return _num(m.group(1))
    if re.search(r"上一章|上章", question):
        return max(1, current - 1)
    if re.search(r"开头|一开始|最初|开局", question):
        return 1
    return None


@router.get("/worlds/{world_id}/memory", response_model=list[MemoryItem])
async def list_memory(world_id: str, kind: str | None = None, limit: int = Query(100, ge=1, le=2000)):
    world_or_404(world_id)
    return [store.to_item(r) for r in store.list_memories(world_id, kind=kind or None, limit=limit)]


@router.post("/worlds/{world_id}/memory/query", response_model=MemoryAnswer)
async def query(world_id: str, body: MemoryQuery):
    w = world_or_404(world_id)
    v = await guard.check_input(body.question, minor_mode=w.minor_mode, rating=w.rating, context="memory_query")
    if v.blocked:
        return MemoryAnswer(answer=v.message or "该问题未通过安全审核。", citations=[])
    cites = await store.search(world_id, body.question, top_k=max(body.top_k * 3, 12))
    tc = target_chapter(body.question, w.state.chapter)
    ranked: list[Citation] = []
    for c in cites:
        sc = c.score
        if tc is not None and c.chapter == tc:
            sc += 0.25 if c.kind != "setting" else 0.05
        if c.kind in ("fact", "event", "injected", "summary") and c.turn > 0:
            sc += 0.05  # 已发生剧情优先于静态设定
        ranked.append(c.model_copy(update={"score": round(sc, 4)}))
    ranked.sort(key=lambda c: -c.score)
    top = ranked[:body.top_k]
    answer = await director.answer_question(w, body.question, top)
    return MemoryAnswer(answer=guard.filter_chunk(answer, minor_mode=w.minor_mode), citations=top, ai_label=AI_LABEL)


@router.get("/worlds/{world_id}/summaries")
async def summaries(world_id: str):
    world_or_404(world_id)
    return [{"chapter": s.chapter, "from_turn": s.from_turn, "to_turn": s.to_turn, "summary": s.summary}
            for s in repo.list_summaries(world_id)]
