"""F1 世界生成 / 列表 / 详情 / 设置。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Response

from app.agents.world_builder import generate_world_events
from app.graph.turn_graph import spawn_opening_media
from app.auth.context import current_owner_id
from app.routes.deps import apply_prefs, owner_prefs, world_or_404
from app.schemas import GenerateWorldRequest, SettingsPatch, World, WorldSummary
from app.services import repo
from app.services.sse import sse_response

router = APIRouter(tags=["worlds"])


@router.post("/worlds/generate")
async def generate(req: GenerateWorldRequest):
    return sse_response(generate_world_events(apply_prefs(req)))


@router.post("/worlds", response_model=World)
async def create(req: GenerateWorldRequest):
    req = apply_prefs(req)
    world, blocked = None, None
    async for name, data in generate_world_events(req):
        if name == "world":
            world = data
        elif name == "safety" and data.get("blocked"):
            blocked = data
    if blocked and not world:
        raise HTTPException(400, blocked.get("message") or "输入未通过安全审核")
    return world


@router.post("/worlds/{world_id}/regenerate")
async def regenerate(world_id: str, overrides: dict[str, Any] | None = Body(default=None)):
    w = world_or_404(world_id)
    base = dict(w.gen_request or w.state.flags.get("gen_request") or {"prompt": w.premise, "mode": w.mode,
                                                                     "rating": w.rating, "minor_mode": w.minor_mode})
    base.pop("wait_details", None)
    # 请求体可选：任意 GenerateWorldRequest 字段作覆盖；refine = 叠加在原始 prompt 上的修改意见（"" 清除）
    base.update({k: v for k, v in (overrides or {}).items() if v is not None and k in GenerateWorldRequest.model_fields})
    if base.get("refine") == "":
        base["refine"] = None
    req = apply_prefs(GenerateWorldRequest(**base))
    edu = w.state.flags.get("edu")

    # 写库阶段在 generate_world_events 内部持有 world_lock（避免与回合/后台补全冲突，且不死锁）
    return sse_response(generate_world_events(req, world_id=world_id, edu=edu))


@router.post("/worlds/{world_id}/confirm", response_model=World)
async def confirm(world_id: str):
    w = world_or_404(world_id)
    if w.status == "draft":
        w.status = "active"
        repo.save_world(w)
        spawn_opening_media(w)
    return w


@router.get("/worlds", response_model=list[WorldSummary])
async def list_worlds():
    return repo.list_worlds(owner_id=current_owner_id() or "")


@router.get("/worlds/{world_id}", response_model=World)
async def get_world(world_id: str):
    return world_or_404(world_id)


@router.delete("/worlds/{world_id}")
async def delete_world(world_id: str):
    world_or_404(world_id)
    if not repo.delete_world(world_id):
        raise HTTPException(404, "世界不存在")
    return {"ok": True}


@router.patch("/worlds/{world_id}/settings", response_model=World)
async def patch_settings(world_id: str, body: SettingsPatch, response: Response):
    from app.auth.prefs import RATING_ORDER, effective

    w = world_or_404(world_id)
    if body.minor_mode is not None:
        w.minor_mode = body.minor_mode
    if body.rating is not None:
        w.rating = body.rating
    # v1.4：账号偏好开启未成年人模式时只能更严格（minor_mode:false 被忽略，rating 封顶），响应头 X-ZM-Clamped 说明
    minor, rating = effective(w.minor_mode, w.rating, owner_prefs())
    clamped = []
    if minor != w.minor_mode:
        clamped.append("minor_mode")
    if RATING_ORDER[rating] < RATING_ORDER[w.rating]:
        clamped.append("rating")
    w.minor_mode, w.rating = minor, rating  # type: ignore[assignment]
    if clamped:
        response.headers["X-ZM-Clamped"] = ",".join(clamped)
    repo.save_world(w)
    return w
