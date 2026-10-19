"""User reports (举报) helpers. The ``reports`` table (``ReportRow``) is owned by backend core; these are
optional helpers (priority triage + CRUD) that routes may use."""
from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import select

from app.db import ReportRow, session_scope
from app.safety import keywords as kw


def _dump(r: ReportRow) -> dict[str, Any]:
    return {"id": r.id, "world_id": r.world_id, "turn_id": r.turn_id, "content": r.content,
            "reason": r.reason, "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else ""}


def report_priority(content: str, reason: str = "") -> str:
    """"high" when the reported content hits hard-block / crisis / injection rules or the reason mentions
    self-harm or minors; else "normal"."""
    text = f"{content}\n{reason}"
    if kw.hard_hits(content) or kw.crisis_match(text) or kw.injection_match(content):
        return "high"
    if any(w in reason for w in ("自杀", "自残", "未成年", "色情", "暴恐", "违法")):
        return "high"
    return "normal"


def create_report(content: str, reason: str, world_id: str | None = None,
                  turn_id: str | None = None) -> dict[str, Any]:
    """Store a report. Reports that hit hard-block keywords are auto-flagged for priority review."""
    status = "received"
    row = ReportRow(id=f"rep_{uuid.uuid4().hex[:12]}", world_id=world_id, turn_id=turn_id,
                    content=content[:5000], reason=reason[:500], status=status)
    with session_scope() as s:
        s.add(row)
    out = _dump(row)
    out["priority"] = report_priority(content, reason)
    return {"id": out["id"], "status": out["status"], "created_at": out["created_at"], "priority": out["priority"]}


def list_reports(world_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(ReportRow)
        if world_id:
            q = q.where(ReportRow.world_id == world_id)
        rows = s.exec(q.order_by(ReportRow.created_at.desc()).limit(limit)).all()
        return [_dump(r) for r in rows]


def update_status(report_id: str, status: str) -> dict[str, Any] | None:
    with session_scope() as s:
        r = s.get(ReportRow, report_id)
        if not r:
            return None
        r.status = status
        s.add(r)
        return _dump(r)
