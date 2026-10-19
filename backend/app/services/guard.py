"""安全接口适配层（后端核心 → app.safety）。

TEAM.md 约定的签名是 ``check_input(text, *, minor_mode, rating, context)`` / ``filter_chunk``；
安全同学的实现可能在演进中（例如改用 ``max_rating``、暂未导出 ``filter_chunk``）。
这里按目标函数的真实签名传参，保证调用方（路由 / 回合图 / 世界生成）不受内部重构影响。
调用顺序（TEAM.md）：check_input → 每个流式片段 filter_chunk → 全文 check_output → 持久化 filtered_text。
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

from app import safety
from app.schemas import SafetyResult

log = logging.getLogger("zhimeng.guard")
SAFE_NOTICE = "（此段内容未通过安全审核，已被替换。故事仍在继续，请换一个方向推进。）"


def _kwargs(fn: Any, *, minor_mode: bool, rating: str | None, context: str | None) -> dict[str, Any]:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        params = {}
    kw: dict[str, Any] = {"minor_mode": minor_mode}
    if rating is not None:
        if "rating" in params:
            kw["rating"] = rating
        elif "max_rating" in params:
            kw["max_rating"] = rating
    if context is not None and "context" in params:
        kw["context"] = context
    return kw


def _coerce(res: Any) -> SafetyResult:
    if isinstance(res, SafetyResult):
        return res
    if isinstance(res, dict):
        return SafetyResult(**res)
    return SafetyResult.model_validate(res, from_attributes=True)


async def check_input(text: str, *, minor_mode: bool = False, rating: str = "teen",
                      context: str = "turn") -> SafetyResult:
    fn = safety.check_input
    try:
        return _coerce(await fn(text, **_kwargs(fn, minor_mode=minor_mode, rating=rating, context=context)))
    except Exception as e:  # noqa: BLE001 - 安全模块异常时保守放行但记录（关键词兜底由 filter_chunk 负责）
        log.exception("safety.check_input failed: %s", e)
        return SafetyResult()


async def check_output(text: str, *, minor_mode: bool = False, rating: str = "teen") -> SafetyResult:
    fn = safety.check_output
    try:
        return _coerce(await fn(text, **_kwargs(fn, minor_mode=minor_mode, rating=rating, context=None)))
    except Exception as e:  # noqa: BLE001
        log.exception("safety.check_output failed: %s", e)
        return SafetyResult(filtered_text=filter_chunk(text, minor_mode=minor_mode))


def filter_chunk(text: str, *, minor_mode: bool = False) -> str:
    """同步快速遮蔽，用于每个流式 token 片段。"""
    fn = getattr(safety, "filter_chunk", None)
    try:
        if fn is not None:
            return fn(text, minor_mode=minor_mode)
        from app.safety import keywords as kw  # 安全同学的关键词表

        if hasattr(kw, "mask_fast"):
            return kw.mask_fast(text, minor_mode=minor_mode)
    except Exception as e:  # noqa: BLE001
        log.warning("filter_chunk failed: %s", e)
    return text


def policy() -> dict[str, Any]:
    return safety.policy()


def crisis_message() -> str:
    return getattr(safety, "CRISIS_MESSAGE", "如需帮助请拨打全国心理援助热线 12356。")


def safety_label() -> str:
    return getattr(safety, "SAFETY_LABEL", "本内容由AI生成，已经过内容安全审核")


class ChunkFilter:
    """流式片段过滤：保留末尾 ``hold`` 个字符，防止敏感词被拆在两个 chunk 之间漏过。"""

    def __init__(self, minor_mode: bool = False, hold: int = 8):
        self.minor_mode, self.hold, self.buf = minor_mode, hold, ""

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        if len(self.buf) <= self.hold * 2:
            return ""
        filtered = filter_chunk(self.buf, minor_mode=self.minor_mode)
        if len(filtered) != len(self.buf):  # 遮蔽改变了长度：整体输出，避免错位
            self.buf = ""
            return filtered
        out, self.buf = filtered[:-self.hold], self.buf[-self.hold:]
        return out

    def flush(self) -> str:
        out, self.buf = filter_chunk(self.buf, minor_mode=self.minor_mode), ""
        return out
