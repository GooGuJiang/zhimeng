"""v1.4 用户系统：注册 / 登录 / 登出 / 刷新 / 当前用户（契约见 API.md「用户系统接口契约」）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request, Response
from fastapi.responses import JSONResponse

from app.auth import ratelimit as rl
from app.auth import security as sec
from app.auth import service as svc
from app.auth import validate as V
from app.auth.context import current_identity
from app.auth.errors import AuthError, token_expired, unauthorized, validation
from app.auth.middleware import cookies_of
from app.auth.prefs import default_prefs
from app.config import get_settings
from app.db import UserRow, session_scope

router = APIRouter(tags=["auth"])


def ip_of(request: Request) -> str:
    return request.scope.get("state", {}).get("zm_ip") or (request.client.host if request.client else "unknown")


def _with_cookies(body: dict[str, Any], status: int, access: str, refresh: str, remember: bool) -> JSONResponse:
    r = JSONResponse(body, status_code=status)
    sec.set_auth_cookies(r, access, refresh, remember=remember)
    return r


def _anon_extra() -> dict[str, Any]:
    req = bool(get_settings().zm_auth_required)
    return {"auth_required": req, "acting_as": None if req else svc.demo_brief()}


@router.post("/auth/register", status_code=201)
async def register(request: Request, body: dict[str, Any] = Body(...)):
    ip = ip_of(request)
    username = V.username(V._s(body, "username"))
    email = V.email(V._s(body, "email"))
    pw = V.password(V._s(body, "password"), username=username, email=email)
    nick_raw = V._s(body, "nickname")
    nickname = username if nick_raw is None or nick_raw == "" else V.nickname(nick_raw)
    await V.safe_text(nickname, "nickname")
    if svc.username_taken(username):
        raise AuthError(409, "username_taken", "用户名已被占用", field="username")
    if email and svc.email_taken(email):
        raise AuthError(409, "email_taken", "该邮箱已被注册", field="email")
    rl.check_window("register", ip, max(1, get_settings().zm_register_per_hour), 3600, "注册太频繁")
    from app.services.repo import new_id
    u = UserRow(id=new_id("u"), username=username, username_lower=username.lower(), email=email,
                password_hash=sec.hash_password(pw), nickname=nickname, preferences=default_prefs())
    with session_scope() as s:
        s.add(u)
    rl.record("register", ip, ip)
    access, refresh = svc.start_session(u, remember=True, user_agent=request.headers.get("user-agent", ""))
    return _with_cookies({"user": svc.user_out(svc.get_user(u.id))}, 201, access, refresh, True)


@router.post("/auth/login")
async def login(request: Request, body: dict[str, Any] = Body(...)):
    ip = ip_of(request)
    login_v = V._s(body, "login") or V._s(body, "username") or V._s(body, "email") or ""
    pw = V._s(body, "password")
    if not 1 <= len(login_v.strip()) <= 254:
        raise validation("login", "请输入用户名或邮箱")
    if not pw:
        raise validation("password", "请输入密码")
    remember = body.get("remember", True)
    remember = remember if isinstance(remember, bool) else True
    rl.check_login(ip, login_v)
    u = svc.find_login(login_v)
    if not u:
        sec.dummy_verify(pw)
    if not u or not sec.verify_password(u.password_hash, pw):
        rl.login_failed(ip, login_v)
        raise AuthError(401, "invalid_credentials", "用户名或密码错误")
    rl.login_ok(ip, login_v)
    access, refresh = svc.start_session(u, remember=remember, user_agent=request.headers.get("user-agent", ""))
    return _with_cookies({"user": svc.user_out(svc.get_user(u.id))}, 200, access, refresh, remember)


@router.post("/auth/logout", status_code=204)
async def logout(request: Request):
    ck = cookies_of({"cookie": request.headers.get("cookie", "")})
    fams = set()
    for name, typ in ((sec.REFRESH_COOKIE, "refresh"), (sec.ACCESS_COOKIE, "access")):
        c = sec.decode(ck.get(name, ""), typ)
        if c and c.get("fam"):
            fams.add(c["fam"])
    for f in fams:
        svc.revoke_family(f)
    r = Response(status_code=204)
    sec.clear_auth_cookies(r)
    return r


@router.post("/auth/refresh")
async def refresh(request: Request):
    rl.hit_refresh(ip_of(request))
    ck = cookies_of({"cookie": request.headers.get("cookie", "")})
    u, access, ref, remember = svc.rotate(ck.get(sec.REFRESH_COOKIE))
    return _with_cookies({"user": svc.user_out(u)}, 200, access, ref, remember)


@router.get("/auth/me")
async def me():
    ident = current_identity()
    if ident and ident.expired:
        raise token_expired(extra=_anon_extra())
    if ident and ident.authenticated:
        u = svc.get_user(ident.user_id)  # type: ignore[arg-type]
        if u:
            return {"authenticated": True, "user": svc.user_out(u), "auth_required": bool(get_settings().zm_auth_required)}
    raise unauthorized(extra=_anon_extra())


@router.patch("/auth/me")
async def patch_me_alias(body: dict[str, Any] = Body(...)):
    """PATCH /api/users/me 的别名（draft2 裁定 7）。"""
    ident = current_identity()
    if ident and ident.expired:
        raise token_expired()
    if not ident or not ident.authenticated:
        raise unauthorized()
    from app.routes.users import update_profile
    return await update_profile(body)
