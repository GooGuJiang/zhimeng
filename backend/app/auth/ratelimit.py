"""限流（记录在 auth_events 表，随数据目录隔离；单进程）。

- 登录：同 IP+login 15 分钟内失败 5 次 → 锁 5 分钟；同 IP 15 分钟内失败 20 次 → 锁 15 分钟；成功清零 IP+login。
- 修改密码：同一用户输错当前密码 5 次 → 锁 5 分钟。
- 注册：同 IP 每小时 ZM_REGISTER_PER_HOUR 次（默认 10）。refresh：同 IP 每分钟 60 次。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlmodel import col, delete, func, select

from app.auth.errors import AuthError

WINDOW = timedelta(minutes=15)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _fmt(sec: int) -> str:
    m, s = divmod(sec, 60)
    return f"{m} 分 {s} 秒" if m else f"{s} 秒"


def _limited(sec: float, what: str = "尝试次数过多") -> AuthError:
    n = max(1, math.ceil(sec))
    return AuthError(429, "rate_limited", f"{what}，请 {_fmt(n)}后再试", retry_after=n)


def _events(kind: str, *, key: str | None = None, ip: str | None = None, since: datetime) -> list[datetime]:
    from app.db import AuthEventRow, session_scope

    with session_scope() as s:
        q = select(AuthEventRow.created_at).where(AuthEventRow.kind == kind, AuthEventRow.created_at >= since)
        if key is not None:
            q = q.where(AuthEventRow.key == key)
        if ip is not None:
            q = q.where(AuthEventRow.ip == ip)
        return sorted(_aware(d) for d in s.exec(q).all())


def record(kind: str, key: str, ip: str = "") -> None:
    from app.db import AuthEventRow, session_scope

    with session_scope() as s:
        s.add(AuthEventRow(kind=kind, key=key, ip=ip))
        n = s.exec(select(func.count()).select_from(AuthEventRow)).one()
        if n > 5000:  # 顺手清理一天前的记录
            s.exec(delete(AuthEventRow).where(col(AuthEventRow.created_at) < _now() - timedelta(days=1)))  # type: ignore[call-overload]


def clear(kind: str, key: str) -> None:
    from app.db import AuthEventRow, session_scope

    with session_scope() as s:
        s.exec(delete(AuthEventRow).where(AuthEventRow.kind == kind, AuthEventRow.key == key))  # type: ignore[call-overload]


def _lock_left(times: list[datetime], limit: int, lock: timedelta) -> float:
    if len(times) < limit:
        return 0.0
    return max(0.0, (times[-1] + lock - _now()).total_seconds())


def login_key(ip: str, login: str) -> str:
    return f"{ip}|{login.strip().lower()}"


def check_login(ip: str, login: str) -> None:
    since = _now() - WINDOW
    left = max(_lock_left(_events("login_fail", key=login_key(ip, login), since=since), 5, timedelta(minutes=5)),
               _lock_left(_events("login_fail", ip=ip, since=since), 20, timedelta(minutes=15)))
    if left > 0:
        raise _limited(left)


def login_failed(ip: str, login: str) -> None:
    record("login_fail", login_key(ip, login), ip)


def login_ok(ip: str, login: str) -> None:
    clear("login_fail", login_key(ip, login))


def check_password_change(user_id: str) -> None:
    left = _lock_left(_events("pwd_fail", key=user_id, since=_now() - WINDOW), 5, timedelta(minutes=5))
    if left > 0:
        raise _limited(left)


def check_window(kind: str, ip: str, limit: int, window_s: float, what: str) -> None:
    window = timedelta(seconds=window_s)
    times = _events(kind, ip=ip, since=_now() - window)
    if len(times) >= limit:
        raise _limited((times[0] + window - _now()).total_seconds(), what)


def hit_refresh(ip: str) -> None:
    check_window("refresh", ip, 60, 60, "请求太频繁")
    record("refresh", ip, ip)
