"""路由公共依赖：按当前身份做归属检查（别人的资源一律 404，不暴露存在性）。"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.auth.context import current_identity
from app.schemas import World
from app.services import repo


def owns(owner_id: str | None) -> bool:
    ident = current_identity()
    if ident is None:  # 无请求上下文（内部调用）
        return True
    return (owner_id or "") == ident.owner_id


def world_or_404(world_id: str, detail: str = "世界不存在") -> World:
    w = repo.load_world(world_id)
    if not w or not owns(w.owner_id):
        raise HTTPException(404, detail)
    return w


def owner_prefs() -> dict[str, Any]:
    from app.auth.prefs import normalize
    from app.auth.service import get_user

    ident = current_identity()
    u = get_user(ident.owner_id) if ident else None
    return normalize(u.preferences if u else None)


def apply_prefs(req: Any, *, minor_default: bool | None = None) -> Any:
    """生成类请求：偏好作为默认值（请求没给的字段），未成年人模式取下限（只能更严格）。"""
    from app.auth.prefs import effective

    p = owner_prefs()
    given = getattr(req, "model_fields_set", set())
    minor = req.minor_mode if "minor_mode" in given else (minor_default if minor_default is not None else p["minor_mode"])
    upd: dict[str, Any] = {}
    if hasattr(req, "rating"):
        rating = req.rating if "rating" in given else p["rating"]
        upd["minor_mode"], upd["rating"] = effective(minor, rating, p)
    else:
        upd["minor_mode"] = effective(minor, "teen", p)[0]
    if hasattr(req, "grade") and not req.grade and p["education"].get("grade"):
        upd["grade"] = p["education"]["grade"]
    if hasattr(req, "subject") and not req.subject and p["education"].get("subject"):
        upd["subject"] = p["education"]["subject"]
    return req.model_copy(update=upd)
