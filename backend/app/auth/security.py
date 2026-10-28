"""密码哈希（argon2id）、JWT 密钥持久化、签发/校验 token、cookie 读写。密钥与密码绝不写日志。"""
from __future__ import annotations

import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import get_settings

ACCESS_COOKIE = "zm_access"
REFRESH_COOKIE = "zm_refresh"
ACCESS_PATH = "/api"
REFRESH_PATH = "/api/auth"
ALG = "HS256"
SESSION_REFRESH_DAYS = 1  # remember:false 时服务端只认 1 天

_ph = PasswordHasher()  # argon2id，库默认参数
_secret_cache: dict[str, str] = {}


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(hashed: str, pw: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


_DUMMY_HASH: str | None = None


def dummy_verify(pw: str) -> None:
    """用户不存在时也做一次哈希校验，避免按耗时判断用户名是否存在。"""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = _ph.hash(secrets.token_urlsafe(16))
    verify_password(_DUMMY_HASH, pw)


def write_secret_file(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def jwt_secret() -> str:
    s = get_settings()
    if s.zm_jwt_secret:
        return s.zm_jwt_secret
    key = str(s.data_dir)
    if key in _secret_cache:
        return _secret_cache[key]
    p = s.data_dir / "jwt_secret"
    val = p.read_text(encoding="utf-8").strip() if p.exists() else ""
    if len(val) < 32:
        val = secrets.token_urlsafe(64)
        write_secret_file(p, val)
    _secret_cache[key] = val
    return val


def now() -> datetime:
    return datetime.now(timezone.utc)


def encode(claims: dict[str, Any], ttl: timedelta) -> str:
    t = now()
    return jwt.encode({**claims, "iat": int(t.timestamp()), "exp": int((t + ttl).timestamp())}, jwt_secret(), algorithm=ALG)


def decode(token: str, typ: str) -> dict[str, Any] | None:
    """签名/过期/类型任一不对 → None（伪造 cookie 一律失败）。"""
    try:
        c = jwt.decode(token, jwt_secret(), algorithms=[ALG], options={"require": ["exp", "sub", "typ"]})
    except jwt.PyJWTError:
        return None
    return c if c.get("typ") == typ else None


def access_ttl() -> timedelta:
    return timedelta(minutes=max(1, get_settings().zm_access_ttl_min))


def refresh_ttl(remember: bool) -> timedelta:
    return timedelta(days=max(1, get_settings().zm_refresh_ttl_days)) if remember else timedelta(days=SESSION_REFRESH_DAYS)


def new_jti() -> str:
    return uuid.uuid4().hex


def set_auth_cookies(resp, access: str, refresh: str, *, remember: bool) -> None:  # noqa: ANN001
    s = get_settings()
    common = {"httponly": True, "samesite": "lax", "secure": bool(s.zm_cookie_secure)}
    resp.set_cookie(ACCESS_COOKIE, access, max_age=int(access_ttl().total_seconds()), path=ACCESS_PATH, **common)
    resp.set_cookie(REFRESH_COOKIE, refresh, max_age=int(refresh_ttl(True).total_seconds()) if remember else None,
                    path=REFRESH_PATH, **common)


def clear_auth_cookies(resp) -> None:  # noqa: ANN001
    s = get_settings()
    for name, path in ((ACCESS_COOKIE, ACCESS_PATH), (REFRESH_COOKIE, REFRESH_PATH)):
        resp.delete_cookie(name, path=path, httponly=True, samesite="lax", secure=bool(s.zm_cookie_secure))
