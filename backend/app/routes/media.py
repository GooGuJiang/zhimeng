"""F5 多模态接口（内部实现属 safety/multimodal 同学，这里只调用 app.multimodal 公共接口）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import multimodal
from app.routes.deps import world_or_404
from app.schemas import Asset, IllustrationRequest, TTSRequest
from app.services import guard, repo

router = APIRouter(tags=["media"])


@router.get("/worlds/{world_id}/assets", response_model=list[Asset])
async def assets(world_id: str):
    world_or_404(world_id)
    return multimodal.list_assets(world_id)


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
    return await multimodal.illustrate(world_id, prompt, turn_id=body.turn_id)


@router.post("/worlds/{world_id}/assets/tts", response_model=Asset)
async def tts(world_id: str, body: TTSRequest):
    w = world_or_404(world_id)
    text = guard.filter_chunk(body.text, minor_mode=w.minor_mode)
    return await multimodal.speak(world_id, text, voice=body.voice, turn_id=body.turn_id)


@router.post("/assets/{asset_id}/regenerate", response_model=Asset)
async def regenerate(asset_id: str):
    a = await multimodal.regenerate(asset_id)
    if not a:
        raise HTTPException(404, "资源不存在")
    return a
