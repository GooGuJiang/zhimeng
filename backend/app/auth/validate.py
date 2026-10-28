"""注册/资料字段校验（错误信息给用户看，中文；附 field）。"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.auth.errors import AuthError, validation

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,19}$")  # 字母开头，3–20 位（前后端统一，AUTH-QA-2）
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESERVED = {"demo", "admin", "root", "system", "zhimeng", "api", "null"}
COMMON_PASSWORDS = {
    "password", "password1", "password12", "password123", "passw0rd", "p@ssw0rd", "12345678", "123456789", "1234567890",
    "qwerty123", "qwertyuiop", "1q2w3e4r", "1qaz2wsx", "abc12345", "abcd1234", "a1234567", "iloveyou1", "admin123",
    "admin1234", "welcome1", "letmein1", "monkey123", "dragon123", "football1", "baseball1", "sunshine1", "princess1",
    "superman1", "trustno1", "11111111", "00000000", "88888888", "66666666", "12341234", "qwer1234", "asdf1234",
    "zxcv1234", "woaini1314", "woaini520", "5201314a", "aa123456", "aa112233", "qq123456", "a12345678", "abc123456",
    "test1234", "test12345", "zhimeng1", "zhimeng123", "changeme1", "default1", "secret123", "master123", "hello123",
    "computer1", "internet1", "shadow123", "michael1", "jordan23", "starwars1", "whatever1", "freedom1", "qazwsx123",
    "1q2w3e4r5t", "zaq12wsx", "q1w2e3r4", "q1w2e3r4t5", "asdfghjkl1", "a1b2c3d4", "1a2b3c4d", "passw0rd1", "abcdefg1",
    "user1234", "login123", "pass1234", "pa55word", "p4ssword", "football123", "ilovechina1", "china123", "beijing2008",
    "a11111111", "qwe123456", "123qweasd", "123qwe123", "qweasd123", "qweasdzxc1", "1234qwer", "1234abcd", "abcd12345",
    "summer2026", "winter2026", "spring2026", "autumn2026", "dream2026", "dream1234", "zhimeng2026",
}


def _s(body: dict[str, Any], key: str) -> str | None:
    v = body.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise validation(key, f"{key} 必须是字符串")
    return v


def username(v: str | None) -> str:
    v = (v or "").strip()
    if not USERNAME_RE.match(v):
        raise validation("username", "用户名需以字母开头，只能包含字母、数字、下划线，长 3–20 位")
    if v.lower() in RESERVED:
        raise AuthError(400, "username_reserved", "这个用户名是保留名，请换一个", field="username")
    return v


def email(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip().lower()
    if not v:
        return None
    if len(v) > 254 or not EMAIL_RE.match(v):
        raise validation("email", "邮箱格式不正确")
    return v


def password(pw: str | None, *, username: str = "", email: str | None = None, field: str = "password") -> str:
    if not isinstance(pw, str) or not pw:
        raise validation(field, "请输入密码")
    if len(pw) < 8 or len(pw) > 64:
        raise AuthError(400, "weak_password", "密码长度需为 8–64 位", field=field)
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"[0-9]", pw)):
        raise AuthError(400, "weak_password", "密码需同时包含字母和数字", field=field)
    low = pw.lower()
    if low == (username or "").lower() or (email and low == email.lower()):
        raise AuthError(400, "weak_password", "密码不能与用户名或邮箱相同", field=field)
    if low in COMMON_PASSWORDS:
        raise AuthError(400, "weak_password", "密码太常见，请换一个更难猜的", field=field)
    return pw


def _has_control(v: str) -> bool:
    return any(unicodedata.category(ch) in ("Cc", "Cf") and ch not in "\n" for ch in v)


def nickname(v: str | None) -> str:
    v = (v or "").strip()
    if not 1 <= len(v) <= 20 or _has_control(v) or "\n" in v:
        raise validation("nickname", "昵称需为 1–20 个字，且不能包含控制字符")
    return v


def bio(v: str | None) -> str:
    v = (v or "").strip()
    if len(v) > 200 or _has_control(v):
        raise validation("bio", "简介最多 200 个字，且不能包含控制字符")
    return v


async def safe_text(v: str, field: str) -> None:
    """昵称/简介过安全规则层（check_input_fast 只取规则层结果，不等 LLM）。"""
    if not v:
        return
    from app.services import guard

    res, review = await guard.check_input_fast(v, minor_mode=False, rating="teen", context="turn")
    if review is not None and hasattr(review, "cancel"):
        review.cancel()  # 资料文本不需要后台 LLM 复核（省费）
    if res.blocked:
        raise AuthError(400, "content_blocked", res.message or "内容未通过安全审核", field=field)
