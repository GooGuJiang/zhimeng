"""《织梦》后端入口：``uvicorn app.main:app``（QA 约定入口固定为 backend/app/main.py:app）。

- 所有接口前缀 /api（契约见 /API.md）；CORS 允许 localhost:3000 / 127.0.0.1:3000
- 生成的插画/配音静态文件挂载在 /api/static/assets/<file>
- GET /api/health 只读配置，不发远程请求（快速）
"""
from __future__ import annotations

import importlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import get_engine

VERSION = "1.0.0"
log = logging.getLogger("zhimeng")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# 路由模块（按功能拆分）；缺失的模块跳过，保证入口始终可导入
ROUTE_MODULES = ["worlds", "play", "memory", "god", "media", "ui", "safety", "education", "save"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_engine()  # 建表
    try:  # 上次进程退出时仍在后台补全的世界：重新排队（或标记 local），避免永远停在 enriching
        from app.agents.world_builder import resume_stale_enrichment
        resume_stale_enrichment()
    except Exception:  # noqa: BLE001
        logging.getLogger("zhimeng").exception("resume stale enrichment failed")
    yield
    try:  # v1.3：优雅关闭时等后台资产升级落库（最多 10s），避免占位永远停在 pending
        from app import multimodal
        await multimodal.drain_background(10)
    except Exception:  # noqa: BLE001
        logging.getLogger("zhimeng").exception("drain multimodal background failed")


settings = get_settings()
app = FastAPI(title="织梦 Zhimeng API", version=VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException):
    code = {400: "bad_request", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "validation_error"}.get(exc.status_code, "error")
    return JSONResponse({"detail": exc.detail, "code": code}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    msg = "; ".join(f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg')}" for e in exc.errors())
    return JSONResponse({"detail": msg or "invalid request", "code": "validation_error"}, status_code=422)


@app.get("/api/health")
async def health():
    from app.llm.client import stats as llm_stats

    s = get_settings()
    st = llm_stats()
    return {"status": "ok", "llm": s.llm_enabled, "fallback": not s.llm_enabled,
            "llm_runtime": {"last_model": st["last_model"], "switches": st["switches"], "cooling": st["cooling"]},
            "models": {"chat": s.chat_model, "fast": s.fast_model, "embedding": s.embedding_model,
                       "image": s.image_model, "tts": s.tts_model,
                       "skeleton": s.skeleton_model, "chat_chain": s.chat_model_chain.split(","),
                       "fast_chain": s.fast_model_chain.split(",")}, "version": VERSION}


for _name in ROUTE_MODULES:
    try:
        _mod = importlib.import_module(f"app.routes.{_name}")
    except ModuleNotFoundError as e:
        if e.name != f"app.routes.{_name}":
            raise
        continue
    app.include_router(_mod.router, prefix="/api")

class AssetFiles(StaticFiles):
    """每次请求按当前配置解析 assets 目录（ZM_DATA_DIR 可在进程内切换，如测试）。"""

    def lookup_path(self, path: str):
        self.all_directories = [str(get_settings().assets_dir)]
        return super().lookup_path(path)


# 静态资源：契约路径 /api/static/assets；/static/assets 作为兼容别名（前端代理两者均可）
app.mount("/api/static/assets", AssetFiles(directory=str(settings.assets_dir), check_dir=False), name="assets")
app.mount("/static/assets", AssetFiles(directory=str(settings.assets_dir), check_dir=False), name="assets_compat")
