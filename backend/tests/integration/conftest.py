"""QA integration smoke fixtures.

Default: run the FastAPI app in-process (fallback mode, temp data dir) via Starlette TestClient.
Set ZM_API_BASE=http://localhost:8000 to hit a live server (e.g. started by scripts/dev.sh, real-model mode).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

LIVE = os.getenv("ZM_API_BASE")
# ZM_QA_REAL=1：进程内但走真实模型（需环境/.env 中的 DASHSCOPE_API_KEY；测试从不打印密钥）
REAL = os.getenv("ZM_QA_REAL", "0").lower() in {"1", "true", "yes"}
DEMO_PROMPT = "一个民国上海滩的侦探故事，我是报社记者"

# 进程内模式：在任何 app.* 导入之前固定兜底模式与临时数据目录，保证可复现
if not LIVE:
    os.environ["ZM_FORCE_FALLBACK"] = "0" if REAL else "1"
    os.environ.setdefault("ZM_DATA_DIR", tempfile.mkdtemp(prefix="zm-qa-"))
    os.environ["STREAM_DELAY"] = "0"


def parse_sse(text: str) -> list[tuple[str, object]]:
    events: list[tuple[str, object]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if not data:
            continue
        raw = "\n".join(data)
        try:
            events.append((name, json.loads(raw)))
        except json.JSONDecodeError:
            events.append((name, raw))
    return events


class Api:
    def __init__(self, client):
        self.c = client

    def get(self, path, **kw):
        return self.c.get(path, **kw)

    def post(self, path, json=None, **kw):
        return self.c.post(path, json=json, **kw)

    def patch(self, path, json=None, **kw):
        return self.c.patch(path, json=json, **kw)

    def delete(self, path, **kw):
        return self.c.delete(path, **kw)

    def sse(self, path, body=None, timeout=180.0):
        r = self.c.post(path, json=body or {}, headers={"Accept": "text/event-stream"}, timeout=timeout)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:300]}"
        assert "text/event-stream" in r.headers.get("content-type", ""), r.headers
        return parse_sse(r.text)


def first(events, name):
    for n, d in events:
        if n == name:
            return d
    return None


def all_of(events, name):
    return [d for n, d in events if n == name]


# ---------------- 账号 / 鉴权（feat/auth，契约：API.md / TEAM.md「用户系统接口契约」「账号/鉴权 QA 契约」v1.4-draft2） ----------------
AUTH_PASSWORD = "Zm-QA-pass-2026!"
LOOPBACK = ("127.0.0.1", 50123)  # 进程内客户端伪装成本机代理，使后端采信 X-Forwarded-For（契约 §5），从而按 IP 隔离限流


def unique_name(prefix: str = "qa") -> str:
    """用户名规则：3–20 位，字母/数字/下划线，不以下划线开头。"""
    return f"{prefix[:8]}_{uuid.uuid4().hex[:8]}"


def unique_ip() -> str:
    """每个测试用户用独立的来源 IP（经 X-Forwarded-For），互不触发注册/登录限流。"""
    h = uuid.uuid4().bytes
    return f"10.{h[0]}.{h[1]}.{h[2] or 1}"


def auth_enabled(client) -> bool:
    """后端是否已实现用户系统：GET /api/auth/me 404 = 未实现（实现后未登录为 401 unauthorized）。"""
    client.cookies.clear()
    return client.get("/api/auth/me").status_code != 404


def auth_required(client) -> bool:
    """draft2：未登录 GET /api/auth/me → 401，body 带 auth_required / acting_as。"""
    client.cookies.clear()
    r = client.get("/api/auth/me")
    try:
        return bool(r.json().get("auth_required"))
    except Exception:  # noqa: BLE001
        return False


def credentials(resp) -> dict[str, str]:
    """注册/登录/refresh 响应里的会话 cookie（zm_access / zm_refresh）→ 显式 Cookie 头。无则 {}。"""
    jar = {k: v for k, v in resp.cookies.items() if v}
    if not jar:
        return {}
    return {"Cookie": "; ".join(f"{k}={v}" for k, v in jar.items())}


def cookie_values(resp) -> dict[str, str]:
    return {k: v for k, v in resp.cookies.items()}


def register_user(client, username: str | None = None, password: str = AUTH_PASSWORD, nickname: str | None = None,
                  ip: str | None = None, **extra):
    username = username or unique_name()
    client.cookies.clear()
    body = {"username": username, "password": password, "nickname": nickname or f"测试{username[-4:]}", **extra}
    return client.post("/api/auth/register", json=body, headers={"X-Forwarded-For": ip or unique_ip()}), username


def login_user(client, login: str, password: str = AUTH_PASSWORD, ip: str | None = None, **extra):
    client.cookies.clear()
    return client.post("/api/auth/login", json={"login": login, "password": password, **extra},
                       headers={"X-Forwarded-For": ip or unique_ip()})


class UserApi(Api):
    """以某个身份发请求：每次清空 cookie 罐，只带显式 Cookie 头（多用户共用一个客户端时不串号）。headers={} 即匿名。"""

    def __init__(self, client, headers: dict[str, str] | None, username: str = "", user: dict | None = None):
        super().__init__(client)
        self.h = dict(headers or {})
        self.username = username
        self.user = user or {}

    def _kw(self, kw):
        self.c.cookies.clear()
        kw["headers"] = {**self.h, **(kw.get("headers") or {})}
        return kw

    def get(self, path, **kw):
        return self.c.get(path, **self._kw(kw))

    def post(self, path, json=None, **kw):
        return self.c.post(path, json=json, **self._kw(kw))

    def put(self, path, json=None, **kw):
        return self.c.put(path, json=json, **self._kw(kw))

    def patch(self, path, json=None, **kw):
        return self.c.patch(path, json=json, **self._kw(kw))

    def delete(self, path, **kw):
        return self.c.delete(path, **self._kw(kw))

    def sse(self, path, body=None, timeout=180.0):
        r = self.post(path, body or {}, headers={"Accept": "text/event-stream"}, timeout=timeout)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:300]}"
        return parse_sse(r.text)


@pytest.fixture(scope="session")
def make_client(api):
    """新建一个独立客户端（独立 cookie 罐），用于多用户隔离测试。依赖 api 以确保应用已启动。"""
    clients = []

    def _new():
        if LIVE:
            import httpx

            c = httpx.Client(base_url=LIVE.rstrip("/"), timeout=180.0)
        else:
            from fastapi.testclient import TestClient

            from app.main import app

            c = TestClient(app, client=LOOPBACK)
        clients.append(c)
        return c

    yield _new
    for c in clients:
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass


def _login_default(c) -> None:
    """ZM_AUTH_REQUIRED=1 时，原有 AC 冒烟用例以一个新注册的 QA 用户身份运行（cookie 罐保存 zm_access/zm_refresh）。
    默认 ZM_AUTH_REQUIRED=0：匿名 = 演示账号 u_demo，原用例不需要登录。"""
    if not auth_enabled(c) or not auth_required(c):
        return
    r, name = register_user(c, unique_name("qadef"))
    assert r.status_code in (200, 201), f"register default QA user -> {r.status_code}: {r.text[:200]}"
    for k, v in r.cookies.items():
        c.cookies.set(k, v)


@pytest.fixture(scope="session")
def api():
    if LIVE:
        import httpx

        with httpx.Client(base_url=LIVE.rstrip("/"), timeout=180.0) as c:
            _login_default(c)
            yield Api(c)
        return
    try:
        from app.main import app  # noqa: F401
    except ModuleNotFoundError as e:  # 后端入口尚未就绪 → 明确失败原因（见 BUGS.md）
        pytest.fail(f"backend entrypoint app.main:app not importable: {e}", pytrace=False)
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, client=LOOPBACK) as c:
        _login_default(c)
        yield Api(c)


@pytest.fixture(scope="session")
def world(api):
    """A confirmed demo world (民国上海滩侦探)."""
    ev = api.sse("/api/worlds/generate", {"prompt": DEMO_PROMPT, "mode": "story", "language": "zh", "rating": "teen"})
    w = first(ev, "world")
    assert w, f"no world event: {[n for n, _ in ev]}"
    r = api.post(f"/api/worlds/{w['id']}/confirm")
    assert r.status_code == 200, r.text
    return r.json()
