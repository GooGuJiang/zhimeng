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
