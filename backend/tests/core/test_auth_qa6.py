"""AUTH-QA-6：可信代理无 XFF 的告警只在 login/register/refresh 上触发，/api/health 不触发。"""
import logging

from app.auth import middleware


def _scope(path):
    return {"client": ("127.0.0.1", 1234), "path": path}


def test_health_does_not_warn(caplog, monkeypatch):
    monkeypatch.setattr(middleware, "_warned_no_xff", False)
    with caplog.at_level(logging.WARNING, logger="zhimeng.auth"):
        assert middleware.client_ip(_scope("/api/health"), {}) is None
    assert "X-Forwarded-For" not in caplog.text
    assert middleware._warned_no_xff is False


def test_login_warns_once(caplog, monkeypatch):
    monkeypatch.setattr(middleware, "_warned_no_xff", False)
    with caplog.at_level(logging.WARNING, logger="zhimeng.auth"):
        middleware.client_ip(_scope("/api/auth/login"), {})
        middleware.client_ip(_scope("/api/auth/register"), {})
    assert sum("X-Forwarded-For" in r.getMessage() for r in caplog.records) == 1


def test_ip_thresholds_configurable(core_env, monkeypatch):
    """原写死的按 IP 阈值可用环境变量调整（ZM_LOGIN_IP_ACCOUNT_MAX_FAILS / ZM_LOGIN_IP_MAX_FAILS）。"""
    from auth_helpers import PW, new_client, register, setenv
    setenv(monkeypatch, ZM_LOGIN_IP_ACCOUNT_MAX_FAILS=2, ZM_LOGIN_ACCOUNT_MAX_FAILS=100)
    with new_client("203.0.113.20") as c:
        _, name = register(c)
        c.cookies.clear()
        for _ in range(2):
            assert c.post("/api/auth/login", json={"login": name, "password": "Wrong#1234"}).status_code == 401
        assert c.post("/api/auth/login", json={"login": name, "password": PW}).status_code == 429
    setenv(monkeypatch, ZM_LOGIN_IP_ACCOUNT_MAX_FAILS=100, ZM_LOGIN_IP_MAX_FAILS=3)
    with new_client("203.0.113.21") as c:
        _, good = register(c)
        c.cookies.clear()
        for i in range(3):
            c.post("/api/auth/login", json={"login": f"nobody{i}x", "password": "Wrong#1234"})
        assert c.post("/api/auth/login", json={"login": good, "password": PW}).status_code == 429


def test_settings_defaults_unchanged(core_env):
    from app.config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert (s.zm_login_ip_account_max_fails, s.zm_login_ip_account_lock_min, s.zm_login_ip_max_fails,
            s.zm_login_ip_lock_min, s.zm_pwd_change_max_fails, s.zm_pwd_change_lock_min,
            s.zm_refresh_per_min, s.zm_login_window_min) == (5, 5, 20, 15, 5, 5, 60, 15)
