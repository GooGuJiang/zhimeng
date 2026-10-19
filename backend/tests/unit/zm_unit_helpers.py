"""Shared helpers for the safety/multimodal unit tests (kept out of conftest.py to avoid module-name clashes)."""
from __future__ import annotations

import httpx

FAKE_KEY = "sk-unittestFAKEKEY0123456789"
REAL_ASYNC_CLIENT = httpx.AsyncClient


def install_transport(monkeypatch, handler) -> list[httpx.Request]:
    """Route every httpx.AsyncClient through ``handler`` (MockTransport). Returns the captured requests."""
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(wrapped)
        return REAL_ASYNC_CLIENT(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return seen
