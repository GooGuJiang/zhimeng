"""Unit-test fixtures for app.safety / app.multimodal: ZM_FORCE_FALLBACK=1 + a temp ZM_DATA_DIR.
Network is never touched: remote paths are exercised with httpx.MockTransport / monkeypatched clients."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zm_unit_helpers import FAKE_KEY, install_transport  # noqa: E402


def _reset():
    from app import db
    from app.config import get_settings
    from app.multimodal import assets, dashscope_api
    from app.safety import engine

    get_settings.cache_clear()
    db.reset_engine()
    assets._recent_fail.clear()
    dashscope_api._tts_model_override = None
    engine._cache.clear()
    engine._cooldown_until = 0.0


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fallback mode, isolated data dir. Returns the fresh Settings object."""
    monkeypatch.setenv("ZM_FORCE_FALLBACK", "1")
    monkeypatch.setenv("ZM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    _reset()
    from app.config import get_settings

    s = get_settings()
    s.dashscope_api_key = None
    yield s
    _reset()


@pytest.fixture
def remote(env, monkeypatch):
    """Pretend a key is configured (remote enabled) — every HTTP call must be mocked by the test."""
    env.dashscope_api_key = FAKE_KEY
    env.force_fallback = False
    from app.multimodal import dashscope_api as ds

    monkeypatch.setattr(ds, "POLL_INTERVAL", 0.0)
    # Guard: any unmocked AsyncClient would try the real network → fail loudly instead.
    def _no_network(request: httpx.Request) -> httpx.Response:  # pragma: no cover - only on test bugs
        raise AssertionError(f"unmocked request to {request.url}")

    install_transport(monkeypatch, _no_network)
    return env
