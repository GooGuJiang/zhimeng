"""账号测试公共工具（不是测试文件）。"""
from __future__ import annotations

import io
import uuid

PW = "Weave#Dream88"
PROMPT = "一个民国上海滩的侦探故事，我是报社记者"


def setenv(monkeypatch, **env) -> None:
    from app.config import get_settings
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    get_settings.cache_clear()


def new_client(ip: str = "127.0.0.1"):
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app, client=(ip, 50000))


def uname(prefix: str = "u") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def register(c, username: str | None = None, password: str = PW, xff: str | None = None, **extra):
    username = username or uname()
    h = {"X-Forwarded-For": xff} if xff else {}
    r = c.post("/api/auth/register", json={"username": username, "password": password, **extra}, headers=h)
    return r, username


def user_client(ip: str = "127.0.0.1"):
    c = new_client(ip)
    r, name = register(c, xff=f"10.9.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250 + 1}")
    assert r.status_code == 201, r.text
    c.zm_name = name  # type: ignore[attr-defined]
    c.zm_user = r.json()["user"]  # type: ignore[attr-defined]
    return c


def png_bytes(w: int = 64, h: int = 40, fmt: str = "PNG") -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


def make_world(c, **body) -> dict:
    r = c.post("/api/worlds", json={"prompt": PROMPT, **body})
    assert r.status_code == 200, r.text
    return r.json()
