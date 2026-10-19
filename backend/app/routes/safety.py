"""F9 安全接口（内部实现属 safety 同学；举报由后端核心存表 reports）。"""
from __future__ import annotations

from fastapi import APIRouter

from app import safety as sf
from app.schemas import ReportRequest, SafetyCheck, SafetyResult
from app.services import guard

router = APIRouter(tags=["safety"])


@router.post("/safety/check", response_model=SafetyResult)
async def check(body: SafetyCheck):
    return await guard.check_input(body.text, minor_mode=body.minor_mode, rating="teen", context="turn")


@router.get("/safety/policy")
async def policy():
    return guard.policy()


@router.post("/reports")
async def report(body: ReportRequest):
    if hasattr(sf, "create_report"):
        r = sf.create_report(body.content, body.reason, world_id=body.world_id, turn_id=body.turn_id)
        return {"id": r["id"], "status": r.get("status", "received"), "created_at": r["created_at"],
                **({"priority": r["priority"]} if "priority" in r else {})}
    import uuid

    from app.db import ReportRow, session_scope
    row = ReportRow(id=f"rep_{uuid.uuid4().hex[:12]}", world_id=body.world_id, turn_id=body.turn_id,
                    content=body.content, reason=body.reason)
    with session_scope() as s:
        s.add(row)
    return {"id": row.id, "status": "received", "created_at": row.created_at.isoformat()}


@router.get("/reports")
async def reports(world_id: str | None = None):
    if hasattr(sf, "list_reports"):
        return sf.list_reports(world_id=world_id)
    from sqlmodel import select

    from app.db import ReportRow, session_scope
    with session_scope() as s:
        q = select(ReportRow)
        if world_id:
            q = q.where(ReportRow.world_id == world_id)
        return [r.model_dump(mode="json") for r in s.exec(q).all()]
