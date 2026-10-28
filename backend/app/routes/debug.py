"""调试接口：GET /api/debug/status（需真实登录或 X-Admin-Token）。不发远程请求，不影响 /api/health。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.auth.context import current_identity
from app.auth.errors import token_expired, unauthorized
from app.config import get_settings

router = APIRouter(tags=["debug"])


@router.get("/debug/status")
async def debug_status() -> dict[str, Any]:
    ident = current_identity()
    if not ident or not (ident.authenticated or ident.admin):
        raise token_expired() if ident and ident.expired else unauthorized()
    mm: Any = None
    try:
        from app import multimodal
        fn = getattr(multimodal, "status", None)
        if callable(fn):
            mm = fn()
    except Exception as e:  # noqa: BLE001 - 调试接口绝不因多模态出错而失败
        mm = {"error": type(e).__name__}
    try:
        from app.llm.client import stats as llm_stats
        st = llm_stats()
        llm = {"last_model": st.get("last_model"), "switches": st.get("switches"), "cooling": st.get("cooling")}
    except Exception:  # noqa: BLE001
        llm = None
    return {"auth_required": bool(get_settings().zm_auth_required), "multimodal": mm, "llm_runtime": llm}
