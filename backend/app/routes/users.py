"""v1.4 个人中心：资料 / 密码 / 头像 / 偏好 / 统计 / 学习记录。"""
from __future__ import annotations

import io
import re
import secrets
from typing import Any

from fastapi import APIRouter, Body, File, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from app.auth import prefs as P
from app.auth import ratelimit as rl
from app.auth import security as sec
from app.auth import service as svc
from app.auth import validate as V
from app.auth.context import current_identity
from app.auth.errors import AuthError, unauthorized, validation
from app.config import get_settings
from app.db import UserRow, session_scope, utcnow

router = APIRouter(tags=["users"])
PRESET_RE = re.compile(r"^preset:[A-Za-z0-9_-]{1,32}$")
AVATAR_PX = 256
MAX_EDGE = 4096


def _me_row(*, real: bool) -> UserRow:
    """real=True：必须真实登录（资料/密码/头像）；否则模式 0 的匿名请求作用于 demo。"""
    ident = current_identity()
    if ident is None:
        raise unauthorized()
    if real and not ident.authenticated:
        raise unauthorized()
    u = svc.get_user(ident.owner_id)
    if not u:
        raise unauthorized()
    return u


def _demo_readonly() -> AuthError:
    return AuthError(403, "demo_readonly", "演示账号不能修改此项")


def _wrong_password(field: str = "current_password") -> AuthError:
    return AuthError(401, "wrong_password", "当前密码不正确", field=field)


@router.get("/users/me")
async def get_me():
    return {"user": svc.user_out(_me_row(real=False))}


async def update_profile(body: dict[str, Any]) -> dict[str, Any]:
    u = _me_row(real=True)
    if u.is_demo:
        raise _demo_readonly()
    changes: dict[str, Any] = {}
    if "nickname" in body:
        changes["nickname"] = V.nickname(V._s(body, "nickname"))
        await V.safe_text(changes["nickname"], "nickname")
    if "bio" in body:
        changes["bio"] = V.bio(V._s(body, "bio"))
        await V.safe_text(changes["bio"], "bio")
    for key in ("avatar_url", "avatar"):  # 兼容前端的预设头像（"preset:<key>"）/ null 清除
        if key in body:
            v = body[key]
            if v is not None and (not isinstance(v, str) or not PRESET_RE.match(v)):
                raise validation(key, "头像只能是预设头像（preset:<key>）或通过上传接口设置")
            changes["avatar_url"] = v
    if "email" in body:
        new_email = V.email(V._s(body, "email"))
        if new_email != u.email:
            if not sec.verify_password(u.password_hash, V._s(body, "current_password") or ""):
                raise _wrong_password()
            if new_email and svc.email_taken(new_email, exclude=u.id):
                raise AuthError(409, "email_taken", "该邮箱已被注册", field="email")
            changes["email"] = new_email
    with session_scope() as s:
        row = s.get(UserRow, u.id)
        old_avatar = row.avatar_url
        for k, v in changes.items():
            setattr(row, k, v)
        if changes:
            row.updated_at = utcnow()
        s.add(row)
    if "avatar_url" in changes and old_avatar != changes["avatar_url"]:
        _delete_avatar_file(old_avatar)
    return {"user": svc.user_out(svc.get_user(u.id))}


@router.patch("/users/me")
async def patch_me(body: dict[str, Any] = Body(...)):
    return await update_profile(body)


@router.api_route("/users/me/password", methods=["POST", "PUT"], status_code=204)
async def change_password(request: Request, body: dict[str, Any] = Body(...)):
    u = _me_row(real=True)
    if u.is_demo:
        raise _demo_readonly()
    rl.check_password_change(u.id)
    cur = V._s(body, "current_password") or V._s(body, "old_password") or ""
    if not sec.verify_password(u.password_hash, cur):
        rl.record("pwd_fail", u.id)
        raise _wrong_password()
    new = V.password(V._s(body, "new_password"), username=u.username, email=u.email, field="new_password")
    if new == cur:
        raise AuthError(400, "same_password", "新密码不能与当前密码相同", field="new_password")
    rl.clear("pwd_fail", u.id)
    with session_scope() as s:
        row = s.get(UserRow, u.id)
        row.password_hash = sec.hash_password(new)
        row.token_version = (row.token_version or 1) + 1
        row.updated_at = utcnow()
        s.add(row)
    svc.revoke_all(u.id)
    fresh = svc.get_user(u.id)
    access, refresh = svc.start_session(fresh, remember=True, user_agent=request.headers.get("user-agent", ""))
    r = Response(status_code=204)
    sec.set_auth_cookies(r, access, refresh, remember=True)
    return r


# ---------------------------------------------------------------- 头像
def _delete_avatar_file(url: str | None) -> None:
    if not url or not url.startswith("/api/static/avatars/"):
        return
    name = url.rsplit("/", 1)[-1].split("?")[0]
    p = get_settings().avatars_dir / name
    try:
        if p.resolve().parent == get_settings().avatars_dir.resolve() and p.exists():
            p.unlink()
    except OSError:
        pass


def _sniff(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    return None


@router.post("/users/me/avatar")
async def upload_avatar(request: Request, file: UploadFile = File(...)):
    u = _me_row(real=True)
    if u.is_demo:
        raise _demo_readonly()
    limit = get_settings().zm_avatar_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AuthError(413, "file_too_large", f"头像不能超过 {limit // (1024 * 1024) or 1} MB")
    kind = _sniff(data[:16])
    if kind is None:
        raise AuthError(415, "unsupported_media_type", "头像只支持 PNG / JPEG / WEBP")
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        im = Image.open(io.BytesIO(data))
        if im.format != kind or im.width > MAX_EDGE or im.height > MAX_EDGE:
            raise ValueError("format/size")
        im.load()
        im = ImageOps.exif_transpose(im)
        im = ImageOps.fit(im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB"), (AVATAR_PX, AVATAR_PX),
                          method=Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, "WEBP", quality=88)  # 重新编码：去掉 EXIF 等元数据
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError) as e:
        raise AuthError(400, "invalid_image", "图片无法识别或尺寸过大（边长不超过 4096）") from e
    name = f"{u.id}_{secrets.token_hex(4)}.webp"
    d = get_settings().avatars_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(out.getvalue())
    url = f"/api/static/avatars/{name}"
    with session_scope() as s:
        row = s.get(UserRow, u.id)
        old = row.avatar_url
        row.avatar_url, row.updated_at = url, utcnow()
        s.add(row)
    _delete_avatar_file(old)
    return {"avatar_url": url, "user": svc.user_out(svc.get_user(u.id))}


@router.delete("/users/me/avatar")
async def delete_avatar():
    u = _me_row(real=True)
    if u.is_demo:
        raise _demo_readonly()
    with session_scope() as s:
        row = s.get(UserRow, u.id)
        old = row.avatar_url
        row.avatar_url, row.updated_at = None, utcnow()
        s.add(row)
    _delete_avatar_file(old)
    return {"avatar_url": None, "user": svc.user_out(svc.get_user(u.id))}


# ---------------------------------------------------------------- 偏好
@router.get("/users/me/preferences")
async def get_prefs():
    return {"preferences": P.normalize(_me_row(real=False).preferences)}


async def _write_prefs(body: dict[str, Any], *, replace: bool) -> dict[str, Any]:
    u = _me_row(real=False)
    body = dict(body or {})
    pw = body.pop("current_password", None)
    if isinstance(body.get("preferences"), dict):
        body = {**body.pop("preferences"), **{k: v for k, v in body.items() if k != "preferences"}}
    old = P.normalize(u.preferences)
    new = P.apply(old, body, replace=replace)
    if old["minor_mode"] and not new["minor_mode"]:
        if u.is_demo:
            raise _demo_readonly()
        if not isinstance(pw, str) or not sec.verify_password(u.password_hash, pw):
            raise _wrong_password()
    with session_scope() as s:
        row = s.get(UserRow, u.id)
        row.preferences, row.updated_at = new, utcnow()
        s.add(row)
    return {"preferences": new}


@router.put("/users/me/preferences")
async def put_prefs(body: dict[str, Any] = Body(...)):
    return await _write_prefs(body, replace=True)


@router.patch("/users/me/preferences")
async def patch_prefs(body: dict[str, Any] = Body(...)):
    return await _write_prefs(body, replace=False)


# ---------------------------------------------------------------- 统计 / 学习记录
@router.get("/users/me/stats")
async def stats():
    return svc.stats(_me_row(real=False).id)


@router.get("/users/me/learning")
async def learning(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return svc.learning(_me_row(real=False).id, limit=limit, offset=offset)


def json_error(e: AuthError) -> JSONResponse:
    return e.response()
