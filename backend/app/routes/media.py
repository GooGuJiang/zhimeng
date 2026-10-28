"""F5 多模态接口（内部实现属 safety/multimodal 同学，这里只调用 app.multimodal 公共接口）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app import multimodal
from app.routes.deps import owns, world_or_404
from app.schemas import Asset, IllustrationRequest, TTSRequest
from app.services import assets as A
from app.services import guard, repo

DEADLINE_S = 8.0  # 同步多媒体端点：超时先返回占位（status=pending），后台完成后同 id 原地升级

router = APIRouter(tags=["media"])


@router.get("/worlds/{world_id}/assets", response_model=list[Asset])
async def assets(world_id: str):
    world_or_404(world_id)
    return A.enrich_all(multimodal.list_assets(world_id))


@router.post("/worlds/{world_id}/assets/illustration", response_model=Asset)
async def illustration(world_id: str, body: IllustrationRequest):
    w = world_or_404(world_id)
    prompt = (body.prompt or "").strip()
    if prompt:
        v = await guard.check_input(prompt, minor_mode=w.minor_mode, rating=w.rating, context="turn")
        if v.blocked:
            raise HTTPException(400, v.message or "插画描述未通过安全审核")
    else:
        narration = w.opening_scene
        if body.turn_id:
            row = repo.get_turn_row(world_id, turn_id=body.turn_id)
            if not row:
                raise HTTPException(404, "回合不存在")
            narration = row.narration
        loc = w.loc(w.state.player_location_id)
        prompt = multimodal.build_scene_prompt(w.model_dump(mode="json"), narration, loc.name if loc else None,
                                               w.minor_mode)
    return A.enrich(await multimodal.illustrate(world_id, prompt, turn_id=body.turn_id, minor_mode=w.minor_mode,
                                                deadline=DEADLINE_S))


@router.post("/worlds/{world_id}/assets/tts", response_model=Asset)
async def tts(world_id: str, body: TTSRequest):
    w = world_or_404(world_id)
    # speak() 没有 minor_mode 参数：配音文本先按世界的未成年人模式/分级过 check_output
    v = await guard.check_output(body.text, minor_mode=w.minor_mode, rating=w.rating)
    if v.blocked:
        raise HTTPException(400, v.message or "配音文本未通过安全审核")
    text = v.filtered_text or body.text
    return A.enrich(await multimodal.speak(world_id, text, voice=body.voice, turn_id=body.turn_id, deadline=DEADLINE_S))


@router.post("/assets/{asset_id}/regenerate", response_model=Asset)
async def regenerate(asset_id: str):
    _asset_or_404(asset_id)
    a = await multimodal.regenerate(asset_id, deadline=DEADLINE_S)
    if not a:
        raise HTTPException(404, "资源不存在")
    return A.enrich(a)


@router.get("/assets/{asset_id}", response_model=Asset)
async def get_asset(asset_id: str, wait: float = Query(0, ge=0, description="长轮询秒数（上限 8）：占位升级完成即返回")):
    _asset_or_404(asset_id)
    a = await A.wait(asset_id, wait) if wait else A.get(asset_id)
    if not a:
        raise HTTPException(404, "资源不存在")
    return a


def _asset_or_404(asset_id: str) -> None:
    """v1.4：资产归属经其 world 判断；别人的资产与不存在一样返回 404。"""
    from app.db import AssetRow, session_scope

    with session_scope() as s:
        row = s.get(AssetRow, asset_id)
        wid = row.world_id if row else None
    if not wid or not owns(repo.world_owner(wid)):
        raise HTTPException(404, "资源不存在")
