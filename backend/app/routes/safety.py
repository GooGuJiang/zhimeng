"""F9 安全接口（内部实现属 safety 同学；举报由后端核心存表 reports）。"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings

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
async def reports(world_id: str | None = None, x_admin_token: str | None = Header(default=None)):
    """按世界查看举报（world_id 必填）；全量列表需 X-Admin-Token == 环境变量 ZM_ADMIN_TOKEN（未设置则禁用全量）。"""
    if not world_id:
        admin = get_settings().zm_admin_token
        if not admin or not x_admin_token or not hmac.compare_digest(admin, x_admin_token):
            raise HTTPException(403, "需要 world_id；全量举报列表仅限管理员（X-Admin-Token）")
    if hasattr(sf, "list_reports"):
        return sf.list_reports(world_id=world_id)
    from sqlmodel import select

    from app.db import ReportRow, session_scope
    with session_scope() as s:
        q = select(ReportRow)
        if world_id:
            q = q.where(ReportRow.world_id == world_id)
        return [r.model_dump(mode="json") for r in s.exec(q).all()]
