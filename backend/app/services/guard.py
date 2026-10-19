"""安全接口适配层（后端核心 → app.safety）。

TEAM.md 约定的签名是 ``check_input(text, *, minor_mode, rating, context)`` / ``filter_chunk``；
安全同学的实现可能在演进中（例如改用 ``max_rating``、暂未导出 ``filter_chunk``）。
这里按目标函数的真实签名传参，保证调用方（路由 / 回合图 / 世界生成）不受内部重构影响。
调用顺序（TEAM.md）：check_input → 每个流式片段 filter_chunk → 全文 check_output → 持久化 filtered_text。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from app import safety
from app.schemas import SafetyResult

log = logging.getLogger("zhimeng.guard")
SAFE_NOTICE = "（此段内容未通过安全审核，已被替换。故事仍在继续，请换一个方向推进。）"


def _kwargs(fn: Any, *, minor_mode: bool, rating: str | None, context: str | None,
            use_llm: bool | None = None) -> dict[str, Any]:
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
    if use_llm is not None and "use_llm" in params:
        kw["use_llm"] = use_llm
    return kw


def _coerce(res: Any) -> SafetyResult:
    if isinstance(res, SafetyResult):
        return res
    if isinstance(res, dict):
        return SafetyResult(**res)
    return SafetyResult.model_validate(res, from_attributes=True)


async def _timed(fn: Any, text: str, kw: dict[str, Any], *, minor_mode: bool, output: bool) -> Any:
    """审核调用时限（guard_timeout_s）：超时（多为大模型审核被限流/断连）→ 只走关键词/规则层（use_llm=False），
    安全模块不支持该参数时 → fail-safe 关键词检查。不会因超时直接放行。"""
    from app.config import get_settings
    try:
        return await asyncio.wait_for(fn(text, **kw), timeout=get_settings().guard_timeout_s)
    except asyncio.TimeoutError:
        log.warning("safety call exceeded %.1fs → rules-only check", get_settings().guard_timeout_s)
        if "use_llm" in inspect.signature(fn).parameters:
            return await fn(text, **{**kw, "use_llm": False})
        return _failsafe(text, minor_mode=minor_mode, output=output)


async def check_input(text: str, *, minor_mode: bool = False, rating: str = "teen",
                      context: str = "turn") -> SafetyResult:
    fn = safety.check_input
    try:
        return _coerce(await _timed(fn, text, _kwargs(fn, minor_mode=minor_mode, rating=rating, context=context),
                                    minor_mode=minor_mode, output=False))
    except Exception as e:  # noqa: BLE001
        log.exception("safety.check_input failed → fail-safe keyword check: %s", e)
        return _failsafe(text, minor_mode=minor_mode, output=False)


async def check_output(text: str, *, minor_mode: bool = False, rating: str = "teen",
                       use_llm: bool | None = None) -> SafetyResult:
    """use_llm=False：只走关键词/规则层（秒级预览用）；None：由安全模块默认策略决定。"""
    fn = safety.check_output
    try:
        return _coerce(await _timed(fn, text, _kwargs(fn, minor_mode=minor_mode, rating=rating, context=None, use_llm=use_llm),
                                    minor_mode=minor_mode, output=True))
    except Exception as e:  # noqa: BLE001
        log.exception("safety.check_output failed → fail-safe keyword check: %s", e)
        return _failsafe(text, minor_mode=minor_mode, output=True)


def _failsafe(text: str, *, minor_mode: bool, output: bool) -> SafetyResult:
    """安全模块自身异常时的兜底（fail-safe，不直接放行）：危机/硬拦截关键词 → 拦截；其余经 filter_chunk 遮蔽。
    关键词库也不可用时：输入拦截（请用户重试），输出替换为安全提示。"""
    try:
        from app.safety import keywords as kw

        if not output and kw.crisis_match(text):
            return SafetyResult(allowed=False, blocked=True, crisis=True, categories=["crisis"], message=crisis_message())
        hard = kw.hard_hits(text) if hasattr(kw, "hard_hits") else kw.find(text, kw.HARD_BLOCK)
        if hard:
            return SafetyResult(allowed=False, blocked=True, categories=sorted(hard), rating="mature",
                                message="内容未通过安全审核，已被拦截。",
                                filtered_text=SAFE_NOTICE if output else None)
        masked = filter_chunk(text, minor_mode=minor_mode)
        return SafetyResult(categories=["safety_degraded"], filtered_text=masked)
    except Exception:  # noqa: BLE001
        log.exception("fail-safe keyword check failed too")
        return SafetyResult(allowed=False, blocked=True, categories=["safety_unavailable"],
                            message="安全审核暂时不可用，请稍后重试。", filtered_text=SAFE_NOTICE if output else None)


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
        if len(self.buf) <= self.hold:  # 只延迟尾部 hold 个字符，其余即刻透传（细粒度增量）
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


# ---------------------------------------------------------------- v1.3 并行快速路径（safety 同学的可选接口）
async def check_input_fast(text: str, *, minor_mode: bool = False, rating: str = "teen", context: str = "turn",
                           on_flag: Any = None) -> tuple[SafetyResult, Any]:
    """规则层结果立即返回 + 可选的后台 LLM 复核任务（命中时回调 on_flag）。安全模块不提供/出错 → 退回完整 check_input。"""
    fn = getattr(safety, "check_input_fast", None)
    if fn is None:
        return await check_input(text, minor_mode=minor_mode, rating=rating, context=context), None
    try:
        rule, review = await asyncio.wait_for(
            fn(text, minor_mode=minor_mode, rating=rating, context=context, on_flag=on_flag),
            timeout=get_settings_timeout())
        return _coerce(rule), review
    except Exception as e:  # noqa: BLE001 - 含超时
        log.warning("check_input_fast failed (%s) → full check_input", type(e).__name__)
        return await check_input(text, minor_mode=minor_mode, rating=rating, context=context), None


def review_output(text: str, *, minor_mode: bool = False, rating: str = "teen", on_flag: Any = None) -> Any:
    """生成文本的后台复核（命中 → on_flag(result)）。没有该接口/无需复核 → None。绝不抛异常。"""
    fn = getattr(safety, "review_output", None)
    if fn is None:
        return None
    try:
        return fn(text, minor_mode=minor_mode, rating=rating, on_flag=on_flag)
    except Exception as e:  # noqa: BLE001
        log.warning("review_output failed: %s", type(e).__name__)
        return None


def get_settings_timeout() -> float:
    from app.config import get_settings
    return get_settings().guard_timeout_s
