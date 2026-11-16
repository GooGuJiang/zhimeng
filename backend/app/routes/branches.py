"""v1.5 角色分支选择：剧情树、路径预览、回到某个节点（另选）。全部按世界归属隔离（别人的世界/节点 → 404）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from app.graph.turn_graph import current_options, world_lock
from app.routes.deps import world_or_404
from app.services import branches, repo

router = APIRouter(tags=["branches"])


@router.get("/worlds/{world_id}/branches")
async def branch_tree(world_id: str):
    return branches.tree(world_or_404(world_id))


@router.get("/worlds/{world_id}/branches/path")
async def branch_path(world_id: str, turn_id: str | None = Query(None, max_length=64)):
    w = world_or_404(world_id)
    try:
        turns = branches.path(w, turn_id)
    except branches.BranchError as e:
        raise HTTPException(404, str(e)) from e
    head = branches.head_row(w)
    return {"head_turn_id": head.id if head else None, "turns": [t.model_dump() for t in turns]}


async def _checkout(world_id: str, target: str | None) -> dict[str, Any]:
    world_or_404(world_id)
    async with world_lock(world_id):
        w = world_or_404(world_id)
        try:
            w = branches.checkout(w, target)
        except branches.BranchError as e:
            raise HTTPException(404, str(e)) from e
    head = branches.head_row(w)
    opts = current_options(w)
    return {"world": w.model_dump(), "turns": [t.model_dump() for t in repo.list_turns(world_id, limit=1000)],
            "options": [o.model_dump() for o in opts], "taken": branches.taken_map(w, head, opts),
            "head_turn_id": head.id if head else None, "branch_id": w.branch_id,
            "current_node_id": head.id if head else branches.OPENING}


@router.post("/worlds/{world_id}/branches/checkout")
async def checkout(world_id: str, body: dict[str, Any] = Body(default={})):
    target = body.get("turn_id") if isinstance(body, dict) else None
    if target is not None and not isinstance(target, str):
        raise HTTPException(422, "turn_id 应为字符串或 null")
    return await _checkout(world_id, target or None)


@router.post("/worlds/{world_id}/branches/rewind")
async def rewind(world_id: str, body: dict[str, Any] = Body(default={})):
    """前端草案里的别名：``{to_node_id}``（"opening" = 开局）。"""
    target = body.get("to_node_id") if isinstance(body, dict) else None
    if target is not None and not isinstance(target, str):
        raise HTTPException(422, "to_node_id 应为字符串")
    return await _checkout(world_id, target or None)
