"""路由公共依赖。"""
from __future__ import annotations

from fastapi import HTTPException

from app.schemas import World
from app.services import repo


def world_or_404(world_id: str) -> World:
    w = repo.load_world(world_id)
    if not w:
        raise HTTPException(404, "世界不存在")
    return w
