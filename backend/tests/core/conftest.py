"""后端核心单元/组件测试夹具：兜底模式 + 临时数据目录 + 禁止任何远程调用。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _reset():
    from app import db
    from app.config import get_settings
    from app.memory import store

    get_settings.cache_clear()
    db.reset_engine()
    store.reset_chroma()


@pytest.fixture
def core_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ZM_FORCE_FALLBACK", "1")
    monkeypatch.setenv("ZM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("STREAM_DELAY", "0")
    _reset()
    from app.llm import client

    def _boom(*a, **k):  # ZM_FORCE_FALLBACK=1 时绝不能创建远程客户端
        raise AssertionError("remote LLM client must not be used in fallback mode")
    monkeypatch.setattr(client, "get_client", _boom)
    yield
    _reset()


@pytest.fixture
def client(core_env):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c
