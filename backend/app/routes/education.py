"""F10 文化/教育模式。"""
from __future__ import annotations

from fastapi import APIRouter

from app.agents import director
from app.agents.world_builder import generate_world_events
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


@router.get("/worlds/{world_id}/education/summary")
async def summary(world_id: str):
    w = world_or_404(world_id)
    timeline = [{"turn": t.index, "summary": f"你{t.action.lstrip('我')}：{t.narration[:60]}"}
                for t in repo.list_turns(world_id, limit=200)]
    s = await director.education_summary(w, timeline)
    return {"title": w.title, "key_points": s["key_points"], "cards": [k.model_dump() for k in w.knowledge_cards],
            "timeline": timeline, "quiz": s["quiz"], "reflection": s["reflection"], "ai_generated": True,
            "ai_label": AI_LABEL}
