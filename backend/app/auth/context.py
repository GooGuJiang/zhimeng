"""当前请求的身份（contextvar；由 AuthMiddleware 在整个请求含 SSE 流期间设置）。"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

DEMO_ID = "u_demo"
DEMO_USERNAME = "demo"


@dataclass(frozen=True)
class Identity:
    user_id: str | None = None      # 真实登录用户；匿名（模式 0）为 None
    session_id: str | None = None   # refresh family
    anonymous: bool = True          # True = 未登录（模式 0 下按 demo 处理）
    admin: bool = False             # 带了正确的 X-Admin-Token
    expired: bool = False           # 带了 zm_access 但无效/过期/已吊销

    @property
    def owner_id(self) -> str:
        return self.user_id or DEMO_ID

    @property
    def authenticated(self) -> bool:
        return self.user_id is not None and not self.anonymous


_ident: ContextVar[Identity | None] = ContextVar("zm_identity", default=None)


def set_identity(ident: Identity | None):  # noqa: ANN201
    return _ident.set(ident)


def reset_identity(token) -> None:  # noqa: ANN001
    _ident.reset(token)


def current_identity() -> Identity | None:
    return _ident.get()


def current_owner_id() -> str | None:
    """当前请求的数据归属（无请求上下文，如启动/后台任务 → None）。"""
    i = _ident.get()
    return i.owner_id if i else None
