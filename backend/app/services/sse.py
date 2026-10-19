"""SSE 工具：事件格式化 + 带正确响应头的 StreamingResponse。"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse

log = logging.getLogger("zhimeng.sse")
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
Event = tuple[str, Any]


def fmt(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _wrap(gen: AsyncIterator[Event]) -> AsyncIterator[str]:
    try:
        async for name, data in gen:
            yield fmt(name, data)
    except asyncio.CancelledError:  # 客户端断开
        raise
    except Exception as e:  # noqa: BLE001 - 任何失败都以 error 事件告知前端（未提交，可重试）
        log.exception("SSE stream failed")
        yield fmt("error", {"message": f"生成失败：{type(e).__name__}，进度未受影响，请重试", "retryable": True})


def sse_response(gen: AsyncIterator[Event]) -> StreamingResponse:
    return StreamingResponse(_wrap(gen), media_type="text/event-stream", headers=SSE_HEADERS)
