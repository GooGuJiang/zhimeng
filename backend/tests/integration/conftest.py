"""QA integration smoke fixtures.

Default: run the FastAPI app in-process (fallback mode, temp data dir) via Starlette TestClient.
Set ZM_API_BASE=http://localhost:8000 to hit a live server (e.g. started by scripts/dev.sh, real-model mode).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

LIVE = os.getenv("ZM_API_BASE")
DEMO_PROMPT = "一个民国上海滩的侦探故事，我是报社记者"


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


@pytest.fixture(scope="session")
def api():
    if LIVE:
        import httpx

        with httpx.Client(base_url=LIVE.rstrip("/"), timeout=180.0) as c:
            yield Api(c)
        return
    tmp = tempfile.mkdtemp(prefix="zm-qa-")
    os.environ["ZM_FORCE_FALLBACK"] = "1"
    os.environ["ZM_DATA_DIR"] = tmp
    os.environ["STREAM_DELAY"] = "0"
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
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
