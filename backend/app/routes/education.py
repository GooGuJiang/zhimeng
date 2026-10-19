"""F10 文化/教育模式。"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from app.agents import director
from app.agents.world_builder import generate_world_events
from app.config import get_settings
from app.llm.client import llm_enabled
from app.routes.deps import world_or_404
from app.schemas import AI_LABEL, EducationGenerateRequest, GenerateWorldRequest, KnowledgeCard
from app.services import repo
from app.services.sse import sse_response

router = APIRouter(tags=["education"])


@router.post("/education/generate")
async def generate(body: EducationGenerateRequest):
    first = body.source_text.strip().splitlines()[0][:40] if body.source_text.strip() else ""
    req = GenerateWorldRequest(prompt=body.title or first, mode="education", source_text=body.source_text,
                               minor_mode=body.minor_mode, rating="all" if body.minor_mode else "teen",
                               genre=f"文化·教育{('·' + body.subject) if body.subject else ''}",
                               wait_details=body.wait_details)
    edu = {"title": body.title, "subject": body.subject, "grade": body.grade}
    return sse_response(generate_world_events(req, edu=edu))


@router.get("/worlds/{world_id}/education/cards", response_model=list[KnowledgeCard])
async def cards(world_id: str):
    return world_or_404(world_id).knowledge_cards


# 学习小结缓存：world_id → (回合数, 结果)；后台 LLM 任务 world_id → Task（BUG-007）
_EDU_CACHE: dict[str, tuple[Any, dict[str, Any]]] = {}
_EDU_JOBS: dict[str, asyncio.Task] = {}


@router.get("/worlds/{world_id}/education/summary")
async def summary(world_id: str):
    """学习小结（向后兼容的同一响应结构，新增 ``status``/``source``）。

    LLM 版在后台任务里生成（快速模型 + 短输入），本请求最多等 ``sync_llm_timeout_s``（默认 8s）：
    - 等到了 / 已缓存（同一回合数）→ ``status:"complete"``；
    - 没等到 → 立即返回本地小结 ``status:"pending", source:"fallback"``，后台继续，稍后再 GET 即得 LLM 版。
    """
    w = world_or_404(world_id)
    turns = repo.list_turns(world_id, limit=200)
    timeline = [{"turn": t.index, "summary": f"你{t.action.lstrip('我')}：{t.narration[:60]}"} for t in turns]
    n = (len(turns), turns[-1].id if turns else "")  # 回合数 + 最后回合 id（重试最后一回合也会失效缓存）

    def shape(s: dict[str, Any], status: str) -> dict[str, Any]:
        return {"title": w.title, "key_points": s["key_points"], "cards": [k.model_dump() for k in w.knowledge_cards],
                "timeline": timeline, "quiz": s["quiz"], "reflection": s["reflection"], "ai_generated": True,
                "ai_label": AI_LABEL, "source": s.get("source", "fallback"), "status": status}

    cached = _EDU_CACHE.get(world_id)
    if cached and cached[0] == n:
        return shape(cached[1], "complete")
    if not llm_enabled() or not w.knowledge_cards:
        s = await director.education_summary(w, timeline, use_llm=False)
        _EDU_CACHE[world_id] = (n, s)
        return shape(s, "complete")
    job = _EDU_JOBS.get(world_id)
    if job is None or job.done():
        async def run(world=w, tl=timeline, count=n) -> dict[str, Any]:
            res = await director.education_summary(world, tl, deadline=45.0)
            if res.get("source") == "llm":
                _EDU_CACHE[world.id] = (count, res)
            return res
        job = asyncio.create_task(run())
        _EDU_JOBS[world_id] = job
    done, _ = await asyncio.wait({job}, timeout=get_settings().sync_llm_timeout_s)
    if job in done and not job.exception():
        res = job.result()
        return shape(res, "complete")
    s = await director.education_summary(w, timeline, use_llm=False)
    return shape(s, "pending")