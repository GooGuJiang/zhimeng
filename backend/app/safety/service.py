"""STUB safety implementation (backend core). The safety engineer replaces the internals;
keep the signatures stable (see /TEAM.md)."""
from __future__ import annotations

from typing import Any

from app.schemas import AI_LABEL, SafetyResult

CRISIS_MESSAGE = (
    "我们注意到你可能正在经历困难。你并不孤单：请拨打全国心理援助热线 12356，"
    "或希望24热线 400-161-9995，紧急情况请拨打 110 / 120。"
)
_CRISIS = ["自杀", "轻生", "不想活", "割腕", "结束生命", "suicide", "kill myself"]
_BLOCK = ["制作炸弹", "毒品配方", "儿童色情"]
_MINOR_BLOCK = ["血腥", "色情", "赌博"]


def _hits(text: str, words: list[str]) -> list[str]:
    low = text.lower()
    return [w for w in words if w.lower() in low]


async def check_input(text: str, *, minor_mode: bool = False, rating: str = "teen",
                      context: str = "turn") -> SafetyResult:
    """Validate user input. ``blocked=True`` → caller must not process it."""
    if _hits(text, _CRISIS):
        return SafetyResult(allowed=False, blocked=True, crisis=True, categories=["crisis"],
                            message=CRISIS_MESSAGE)
    bad = _hits(text, _BLOCK) + (_hits(text, _MINOR_BLOCK) if minor_mode else [])
    if bad:
        return SafetyResult(allowed=False, blocked=True, categories=["prohibited"],
                            message="输入包含不适宜内容，已被拦截。请换一种说法。")
    return SafetyResult(rating="all" if minor_mode else rating)  # type: ignore[arg-type]


async def check_output(text: str, *, minor_mode: bool = False, rating: str = "teen") -> SafetyResult:
    """Validate generated text. ``filtered_text`` is what may be shown/persisted."""
    return SafetyResult(filtered_text=filter_chunk(text, minor_mode=minor_mode),
                        rating="all" if minor_mode else rating)  # type: ignore[arg-type]


def filter_chunk(text: str, *, minor_mode: bool = False) -> str:
    """Fast synchronous masking for streamed tokens."""
    for w in _BLOCK + (_MINOR_BLOCK if minor_mode else []):
        text = text.replace(w, "＊" * len(w))
    return text


def policy() -> dict[str, Any]:
    return {"ratings": ["all", "teen", "mature"],
            "minor_mode": {"forces_rating": "all", "description": "未成年人模式：更严格过滤，禁用成人题材"},
            "crisis_message": CRISIS_MESSAGE, "ai_label": AI_LABEL}
