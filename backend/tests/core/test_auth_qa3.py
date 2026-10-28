"""AUTH-QA-3：伪造 XFF / 代理不传 XFF 时的限流兜底（按账号上限、只取 XFF 最右项、IP 未知、全站注册上限）。"""
from __future__ import annotations

import logging

from auth_helpers import PW, new_client, register, setenv, uname

PROXY = "172.21.0.3"  # 模拟前端容器（可信代理）


def code(r):
    return r.json().get("code")


def _env(monkeypatch, **kw):
    setenv(monkeypatch, ZM_TRUSTED_PROXIES="127.0.0.1/32,::1,172.16.0.0/12", **kw)


def _login(c, login, pw, xff=None):
    return c.post("/api/auth/login", json={"login": login, "password": pw},
                  headers={"X-Forwarded-For": xff} if xff else {})


def test_rightmost_xff_only(core_env, monkeypatch):
    from app.auth.middleware import client_ip
    _env(monkeypatch)
    ip = lambda xff: client_ip({"client": (PROXY, 1)}, {"x-forwarded-for": xff})  # noqa: E731
    assert ip("1.1.1.1, 2.2.2.2, 198.51.100.7") == "198.51.100.7"
    assert ip("1.1.1.1, 10.0.0.9") == "10.0.0.9"       # 不再跳过可信地址往左回溯
    assert ip("garbage") is None
    setenv(monkeypatch, ZM_PROXY_HOPS=2)
    assert ip("1.1.1.1, 198.51.100.7, 172.21.0.9") == "198.51.100.7"
    assert ip("198.51.100.7") is None                  # 条目不足 → 未知
    assert client_ip({"client": (PROXY, 1)}, {}) is None                       # 可信对端无 XFF → 未知
    assert client_ip({"client": ("203.0.113.5", 1)}, {"x-forwarded-for": "1.2.3.4"}) == "203.0.113.5"


def test_forged_xff_cannot_bypass_account_limit(core_env, monkeypatch):
    _env(monkeypatch)
    with new_client(PROXY) as c:
        _, name = register(c, xff="198.51.100.1")
        c.cookies.clear()
        for i in range(10):  # 每次伪造不同 XFF：按 IP 的规则全绕过，但按账号计数
            r = _login(c, name, "Wrong#1234", xff=f"9.9.{i}.{i + 1}")
            assert code(r) == "invalid_credentials", (i, r.text)
        r = _login(c, name, PW, xff="9.9.99.99")  # 锁定期间正确密码也 429
        assert r.status_code == 429 and code(r) == "rate_limited" and 0 < r.json()["retry_after"] <= 900
        assert int(r.headers["Retry-After"]) == r.json()["retry_after"]
        r = _login(c, name.upper(), PW)          # 换大小写 / 无 XFF 同样锁
        assert r.status_code == 429


def test_account_counter_not_reset_by_success(core_env, monkeypatch):
    _env(monkeypatch, ZM_LOGIN_ACCOUNT_MAX_FAILS=4)
    with new_client(PROXY) as c:
        _, name = register(c, xff="198.51.100.2")
        c.cookies.clear()
        for i in range(3):
            _login(c, name, "Wrong#1234", xff=f"8.8.{i}.1")
        assert _login(c, name, PW, xff="8.8.50.1").status_code == 200  # 成功登录不清零按账号计数
        _login(c, name, "Wrong#1234", xff="8.8.51.1")
        assert _login(c, name, PW, xff="8.8.52.1").status_code == 429


def test_account_limit_uses_user_id_across_username_and_email(core_env, monkeypatch):
    _env(monkeypatch, ZM_LOGIN_ACCOUNT_MAX_FAILS=4)
    with new_client(PROXY) as c:
        _, name = register(c, xff="198.51.100.3", email="mix@x.com")
        c.cookies.clear()
        for i, login in enumerate([name, "MIX@x.com", name, "mix@x.com"]):
            _login(c, login, "Wrong#1234", xff=f"7.7.{i}.1")
        assert _login(c, "mix@x.com", PW, xff="7.7.9.1").status_code == 429


def test_unknown_username_counted_same_response(core_env, monkeypatch):
    _env(monkeypatch, ZM_LOGIN_ACCOUNT_MAX_FAILS=3)
    with new_client(PROXY) as c:
        _, name = register(c, xff="198.51.100.4")
        c.cookies.clear()
        ghost = "ghost_" + uname()
        real = [_login(c, name, "Wrong#1234", xff=f"6.6.{i}.1") for i in range(3)]
        fake = [_login(c, ghost, "Wrong#1234", xff=f"6.7.{i}.1") for i in range(3)]
        for a, b in zip(real, fake):
            assert (a.status_code, a.json()) == (b.status_code, b.json())
        ra, rb = _login(c, name, "Wrong#1234", xff="6.6.9.1"), _login(c, ghost.upper(), "Wrong#1234", xff="6.7.9.1")
        assert ra.status_code == rb.status_code == 429
        assert code(ra) == code(rb) == "rate_limited" and ra.json()["detail"] == rb.json()["detail"]


def test_no_xff_traffic_does_not_lock_unrelated_users(core_env, monkeypatch, caplog):
    _env(monkeypatch)
    import app.auth.middleware as mw
    mw._warned_no_xff = False
    caplog.set_level(logging.WARNING, logger="zhimeng.auth")
    with new_client(PROXY) as c:  # 代理没传 XFF：客户端 IP 未知
        users = [register(c, xff=f"198.51.100.{20 + i}")[1] for i in range(6)]
        c.cookies.clear()
        for i in range(25):  # 5 个账号累计 25 次失败（旧实现：同一 IP 20 次 → 全站锁 15 分钟）
            assert code(_login(c, users[i % 5], "Wrong#1234")) == "invalid_credentials"
        assert _login(c, users[5], PW).status_code == 200  # 无关账号不受影响
        assert sum("没有 X-Forwarded-For" in r.message for r in caplog.records) == 1  # 只告警一次
        for i in range(12):  # 注册：每 IP 上限（10/小时）对 IP 未知的请求不生效
            assert register(c)[0].status_code == 201, i


def test_global_register_limit(core_env, monkeypatch):
    _env(monkeypatch, ZM_REGISTER_GLOBAL_PER_HOUR=3, ZM_REGISTER_PER_HOUR=100)
    with new_client(PROXY) as c:
        assert register(c, xff="198.51.100.30")[0].status_code == 201
        assert register(c)[0].status_code == 201                       # IP 未知
        assert register(c, xff="198.51.100.31")[0].status_code == 201
        r = register(c, xff="198.51.100.32")[0]
        assert r.status_code == 429 and code(r) == "rate_limited" and r.json()["retry_after"] > 0
        assert register(c)[0].status_code == 429
