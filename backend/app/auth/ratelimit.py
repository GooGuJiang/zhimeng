"""限流（记录在 auth_events 表，随数据目录隔离；单进程）。

- 登录（IP 已知时）：同 IP+login 15 分钟内失败 5 次 → 锁 5 分钟（成功清零）；同 IP 15 分钟内失败 20 次 → 锁 15 分钟。
- 登录（兜底，与 IP 无关，AUTH-QA-3）：同一账号 ZM_LOGIN_ACCOUNT_WINDOW_MIN（15）分钟内失败
  ZM_LOGIN_ACCOUNT_MAX_FAILS（10）次 → 锁 ZM_LOGIN_ACCOUNT_LOCK_MIN（15）分钟；成功**不**清零；不存在的用户名同样计数。
- 客户端 IP 未知（ip=None：可信代理没传 XFF）→ 按 IP 的规则都不生效，只剩按账号上限与全站注册上限。
- 修改密码：同一用户输错当前密码 5 次 → 锁 5 分钟。
- 注册：同 IP 每小时 ZM_REGISTER_PER_HOUR（10）次；全站每小时 ZM_REGISTER_GLOBAL_PER_HOUR（200）次。
- refresh：同 IP 每分钟 60 次（IP 未知时不限）。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlmodel import col, delete, func, select

from app.auth.errors import AuthError
from app.config import get_settings

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


def _acct_left(acct: str) -> float:
    s = get_settings()
    times = _events("login_fail_acct", key=acct, since=_now() - timedelta(minutes=max(1, s.zm_login_account_window_min)))
    return _lock_left(times, max(1, s.zm_login_account_max_fails), timedelta(minutes=max(1, s.zm_login_account_lock_min)))


def check_login(ip: str | None, login: str, acct: str) -> None:
    left = _acct_left(acct)
    if ip is not None:
        since = _now() - WINDOW
        left = max(left, _lock_left(_events("login_fail", key=login_key(ip, login), since=since), 5, timedelta(minutes=5)),
                   _lock_left(_events("login_fail", ip=ip, since=since), 20, timedelta(minutes=15)))
    if left > 0:
        raise _limited(left)


def login_failed(ip: str | None, login: str, acct: str) -> None:
    record("login_fail_acct", acct, ip or "")
    if ip is not None:
        record("login_fail", login_key(ip, login), ip)


def login_ok(ip: str | None, login: str) -> None:
    if ip is not None:
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


def _global_count(kind: str, window: timedelta) -> int:
    from app.db import AuthEventRow, session_scope

    with session_scope() as s:
        return int(s.exec(select(func.count()).select_from(AuthEventRow)
                          .where(AuthEventRow.kind == kind, AuthEventRow.created_at >= _now() - window)).one())


def check_register(ip: str | None) -> None:
    s = get_settings()
    hour = timedelta(hours=1)
    if _global_count("register", hour) >= max(1, s.zm_register_global_per_hour):
        times = _events("register", since=_now() - hour)
        raise _limited((times[0] + hour - _now()).total_seconds() if times else 60, "注册人数过多")
    if ip is not None:
        check_window("register", ip, max(1, s.zm_register_per_hour), 3600, "注册太频繁")


def hit_refresh(ip: str | None) -> None:
    if ip is None:
        return
    check_window("refresh", ip, 60, 60, "请求太频繁")
    record("refresh", ip, ip)
