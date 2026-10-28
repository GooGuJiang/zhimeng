"""统一的鉴权/用户错误：{detail, code, field?, retry_after?}（沿用 API.md 错误风格）。"""
from __future__ import annotations

from typing import Any


class AuthError(Exception):
    def __init__(self, status: int, code: str, detail: str, *, field: str | None = None,
                 retry_after: int | None = None, extra: dict[str, Any] | None = None,
                 clear_cookies: bool = False) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail
        self.field, self.retry_after, self.extra = field, retry_after, extra or {}
        self.clear_cookies = clear_cookies

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"detail": self.detail, "code": self.code}
        if self.field:
            out["field"] = self.field
        if self.retry_after is not None:
            out["retry_after"] = self.retry_after
        out.update(self.extra)
        return out

    def response(self):  # noqa: ANN201
        from fastapi.responses import JSONResponse

        r = JSONResponse(self.body(), status_code=self.status)
        if self.retry_after is not None:
            r.headers["Retry-After"] = str(self.retry_after)
        if self.clear_cookies:
            from app.auth.security import clear_auth_cookies
            clear_auth_cookies(r)
        return r


def unauthorized(detail: str = "请先登录", **kw: Any) -> AuthError:
    return AuthError(401, "unauthorized", detail, **kw)


def token_expired(**kw: Any) -> AuthError:
    return AuthError(401, "token_expired", "登录已过期，请重新登录", **kw)


def validation(field: str, detail: str) -> AuthError:
    return AuthError(422, "validation_error", detail, field=field)
