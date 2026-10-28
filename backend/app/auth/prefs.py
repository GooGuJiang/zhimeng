"""用户偏好：默认值、PUT 整体覆盖 / PATCH 部分合并的校验，以及「偏好是下限」的未成年人模式/分级收紧规则。"""
from __future__ import annotations

import copy
import os
from typing import Any

from app.auth.errors import validation

RATING_ORDER = {"all": 0, "teen": 1, "mature": 2}

DEFAULTS: dict[str, Any] = {
    "minor_mode": False, "rating": "teen", "tts_enabled": True, "autoplay_audio": False, "show_god_view": True,
    "education": {"grade": None, "subject": None, "auto_summary": True}, "language": "zh",
}
_BOOL = ("minor_mode", "tts_enabled", "autoplay_audio", "show_god_view")


def default_prefs() -> dict[str, Any]:
    return copy.deepcopy(DEFAULTS)


def normalize(stored: dict[str, Any] | None) -> dict[str, Any]:
    """库里的偏好（可能缺字段/旧版）→ 完整 Preferences。"""
    out = default_prefs()
    for k, v in (stored or {}).items():
        if k == "education" and isinstance(v, dict):
            out["education"].update({kk: vv for kk, vv in v.items() if kk in out["education"]})
        elif k in out:
            out[k] = v
    return out


def _check(patch: dict[str, Any]) -> None:
    for k, v in patch.items():
        if k not in DEFAULTS:
            raise validation(k, f"未知的偏好字段：{k}")
        if k in _BOOL and not isinstance(v, bool):
            raise validation(k, f"{k} 必须是 true/false")
        if k == "rating" and v not in RATING_ORDER:
            raise validation(k, "rating 只能是 all / teen / mature")
        if k == "language" and v != "zh":
            raise validation(k, "language 目前只支持 zh")
        if k == "education":
            if not isinstance(v, dict):
                raise validation(k, "education 必须是对象")
            for kk, vv in v.items():
                if kk not in DEFAULTS["education"]:
                    raise validation(f"education.{kk}", f"未知的偏好字段：education.{kk}")
                if kk == "auto_summary" and not isinstance(vv, bool):
                    raise validation("education.auto_summary", "auto_summary 必须是 true/false")
                if kk in ("grade", "subject") and vv is not None and (not isinstance(vv, str) or len(vv) > 20):
                    raise validation(f"education.{kk}", f"{kk} 须为不超过 20 字的文本或 null")


def apply(current: dict[str, Any], body: dict[str, Any], *, replace: bool) -> dict[str, Any]:
    """PUT（replace=True，缺的字段回到默认值）/ PATCH（部分合并，education 也部分合并）。"""
    _check(body)
    base = default_prefs() if replace else normalize(current)
    for k, v in body.items():
        if k == "education":
            base["education"].update(v)
        else:
            base[k] = v
    return base


def minor_max_rating() -> str:
    r = os.getenv("ZM_MINOR_MAX_RATING", "teen")
    return r if r in RATING_ORDER else "teen"


def min_rating(*rs: str) -> str:
    return min((r for r in rs if r in RATING_ORDER), key=lambda x: RATING_ORDER[x], default="teen")


def effective(minor_mode: bool, rating: str, prefs: dict[str, Any] | None) -> tuple[bool, str]:
    """未成年人模式取下限：minor = 请求 OR 偏好（只能更严格）；minor 时 rating 封顶 ZM_MINOR_MAX_RATING（默认 teen）。
    rating 本身：请求没给时由调用方取偏好的 rating 作为默认值，给了就以请求为准（不额外设上限，避免破坏现有行为）。"""
    p = normalize(prefs)
    minor = bool(minor_mode) or bool(p["minor_mode"])
    r = rating if rating in RATING_ORDER else p["rating"]
    if minor:
        r = min_rating(r, minor_max_rating())
    return minor, r
