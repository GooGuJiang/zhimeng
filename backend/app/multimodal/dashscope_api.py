"""Thin async client for DashScope native APIs (image synthesis + speech synthesis).

Docs checked 2026-10:
- 文生图 (wan2.5 及以下, 旧版协议, 异步):  POST {api}/services/aigc/text2image/image-synthesis
  header ``X-DashScope-Async: enable``; body {model, input:{prompt, negative_prompt}, parameters:{size,n,prompt_extend,watermark}}
  → output.task_id; poll GET {api}/tasks/{task_id} until task_status SUCCEEDED → output.results[0].url (24h)
- 语音合成 Qwen-TTS:  POST {api}/services/aigc/multimodal-generation/generation
  body {model:"qwen-tts"|"qwen3-tts-flash", input:{text, voice, language_type}} → output.audio.url (wav, 24h)
Verified 2026-10-19 against help.aliyun.com/zh/model-studio/text-to-image-v2-api-reference (wanx2.1: prompt ≤500
chars, size 宽高∈[512,1440], n default 4 → we always send n=1, watermark adds "AI生成") and
help.aliyun.com/zh/model-studio/qwen-tts-api (text ≤600 chars, language_type optional, audio.url valid 24h).
The API key is read from settings and sent only in the Authorization header (never to the OSS result URLs);
it is never logged, written to disk or put into exception messages (``redact``).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger("zhimeng.multimodal")


WATERMARK = os.getenv("ZM_IMAGE_WATERMARK", "1").lower() not in {"0", "false", "no"}  # explicit AI label


def redact(text: object) -> str:
    """Remove the API key (and anything that looks like a bearer token) from a string before logging."""
    import re

    out = str(text)
    key = get_settings().dashscope_api_key
    if key:
        out = out.replace(key, "sk-***")
    return re.sub(r"sk-[A-Za-z0-9]{8,}", "sk-***", out)


def images_disabled() -> bool:
    """``ZM_DISABLE_IMAGE=1|true|yes`` → never call the image API (placeholder SVG only, cost saving).
    Owned by backend ``config.py`` (``Settings.disable_image`` / ``image_enabled``); checked on every call so a
    running background job stops too. getattr defaults keep older Settings versions working."""
    s = get_settings()
    return bool(getattr(s, "disable_image", False))


class DashScopeError(RuntimeError):
    def __init__(self, code: str, message: str = "", retryable: bool = False, status: int | None = None):
        super().__init__(redact(f"{code}: {message[:200]}"))
        self.code = code
        self.retryable = retryable
        self.status = status


# Codes that mean "the network / transport failed", not "the content or request is wrong".
NETWORK_CODES = {"DownloadFailed", "Timeout", "EmptyAudio"}


def is_network_error(e: BaseException) -> bool:
    """Network / transport / server-side failures (worth a delayed retry). 4xx content/request errors are not."""
    if isinstance(e, (httpx.TransportError, asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True
    if isinstance(e, DashScopeError):
        if e.code in NON_RETRYABLE:
            return False
        if e.status is not None:
            return e.status >= 500
        return e.code in NETWORK_CODES
    return False


def _guard_image() -> None:
    if images_disabled():
        raise DashScopeError("ImageDisabled", "ZM_DISABLE_IMAGE is set")


NON_RETRYABLE = {"DataInspectionFailed", "IPInfringementSuspect", "InvalidApiKey", "InvalidParameter",
                 "Arrearage", "AccessDenied", "Model.AccessDenied"}

# BUG-002: "qwen-tts" answers 404 "Model not exist." for current keys; the documented non-realtime model is
# qwen3-tts-flash (https://help.aliyun.com/zh/model-studio/qwen-tts-api, same endpoint, voices Cherry/Serena/
# Ethan/Chelsie/...). Known-unavailable names are mapped; any other "Model not exist" retries with this model.
TTS_FALLBACK_MODEL = "qwen3-tts-flash"
TTS_MODEL_ALIASES = {"qwen-tts": TTS_FALLBACK_MODEL, "qwen-tts-latest": TTS_FALLBACK_MODEL}
_tts_model_override: str | None = None  # set after a runtime "Model not exist" → sticky for the process


def effective_tts_model() -> str:
    m = _tts_model_override or get_settings().tts_model or TTS_FALLBACK_MODEL
    return TTS_MODEL_ALIASES.get(m, m)


def _model_missing(e: Exception) -> bool:
    msg = str(e).lower()
    return "model not exist" in msg or "model_not_found" in msg or "modelnotfound" in msg


CONNECT_TIMEOUT = float(os.getenv("ZM_MM_CONNECT_TIMEOUT", "10"))
READ_TIMEOUT = float(os.getenv("ZM_MM_READ_TIMEOUT", "30"))
NET_RETRIES = int(os.getenv("ZM_MM_NET_RETRIES", os.getenv("ZM_MM_CONNECT_RETRIES", "3")))
BACKOFF_BASE = float(os.getenv("ZM_MM_BACKOFF_BASE", "0.5"))  # 0.5s → 1s → 2s … (capped at 8s)

# "Not sent" errors: the request never reached the server → retrying a billing POST cannot double-charge.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
# Any transport error (incl. ReadError / RemoteProtocolError / ReadTimeout / server silently closed the socket)
# is fine to retry for idempotent GETs (task polling, result download).
_TRANSPORT = (httpx.TransportError,)


def _client() -> httpx.AsyncClient:
    """A fresh client per request, keep-alive disabled: long-lived connections from this box to DashScope are
    often dropped after a few seconds or closed silently, so we never reuse a pooled connection."""
    s = get_settings()
    return httpx.AsyncClient(timeout=httpx.Timeout(max(READ_TIMEOUT, min(s.llm_timeout, 120.0)), connect=CONNECT_TIMEOUT),
                             limits=httpx.Limits(max_keepalive_connections=0, keepalive_expiry=0),
                             headers={"Connection": "close"})


async def _request(method: str, url: str, *, idempotent: bool | None = None, **kw: Any) -> httpx.Response:
    """One request on a fresh connection, with bounded exponential-backoff retries.

    ``idempotent`` (default: GET) → retry on any transport error; otherwise (task-creating / billed POSTs) retry
    only when the request provably was not sent (connect errors). HTTP status errors are never retried here.
    """
    idem = (method.upper() == "GET") if idempotent is None else idempotent
    retry_on = _TRANSPORT if idem else _NOT_SENT
    for attempt in range(NET_RETRIES + 1):
        try:
            async with _client() as client:
                r = await client.request(method, url, **kw)
                await r.aread()
                return r
        except retry_on as e:
            if attempt >= NET_RETRIES:
                raise
            STATS["net_retries"] += 1
            delay = min(8.0, BACKOFF_BASE * (2 ** attempt))
            log.info("%s %s network error (%s), retry %d in %.1fs", method, httpx.URL(url).host,
                     type(e).__name__, attempt + 1, delay)
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


STATS: dict[str, int] = {"net_retries": 0}


def _https_first(url: str) -> list[str]:
    """Result URLs (OSS, signed) are sometimes plain http:// — many networks block port 80, and OSS serves the
    same signed URL over https (the signature does not cover the scheme). Try https first, then the original."""
    u = httpx.URL(url)
    if u.scheme == "http" and u.host.endswith(".aliyuncs.com"):
        return [str(u.copy_with(scheme="https")), url]
    return [url]


async def _download(url: str) -> bytes:
    last: Exception | None = None
    for candidate in _https_first(url):
        try:
            r = await _request("GET", candidate)  # result URLs: never send the Authorization header
            r.raise_for_status()
            return r.content
        except (httpx.HTTPError,) as e:
            last = e
    raise DashScopeError("DownloadFailed", f"{type(last).__name__}: {last}")


# Overridable for tests (avoid real sleeps).
POLL_INTERVAL = float(os.getenv("ZM_MM_POLL_INTERVAL", "2"))
POLL_TIMEOUT = float(os.getenv("ZM_MM_POLL_TIMEOUT", "120"))


def _headers(async_task: bool = False) -> dict[str, str]:
    s = get_settings()
    if not s.dashscope_api_key or s.force_fallback:
        raise DashScopeError("NoApiKey", "remote calls disabled")
    h = {"Authorization": f"Bearer {s.dashscope_api_key}", "Content-Type": "application/json"}
    if async_task:
        h["X-DashScope-Async"] = "enable"
    return h


def _raise_for(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400 or data.get("code"):
        code = str(data.get("code") or f"HTTP{resp.status_code}")
        raise DashScopeError(code, str(data.get("message", "")),
                             retryable=resp.status_code in (429, 500, 502, 503, 504) and code not in NON_RETRYABLE,
                             status=resp.status_code if resp.status_code >= 400 else None)
    return data


async def create_image_task(prompt: str, negative_prompt: str = "",
                            size: str = "1280*720", model: str | None = None, seed: int | None = None) -> str:
    _guard_image()
    s = get_settings()
    params: dict[str, Any] = {"size": size, "n": 1, "prompt_extend": False, "watermark": WATERMARK}
    if seed is not None:
        params["seed"] = seed
    body = {"model": model or s.image_model,
            "input": {"prompt": prompt[:500], "negative_prompt": negative_prompt[:500]},
            "parameters": params}
    r = await _request("POST", f"{s.dashscope_api_url}/services/aigc/text2image/image-synthesis",
                       headers=_headers(async_task=True), json=body)  # billed: retried only if not sent
    data = _raise_for(r)
    task_id = (data.get("output") or {}).get("task_id")
    if not task_id:
        raise DashScopeError("NoTaskId", str(data)[:200])
    return task_id


async def poll_task(task_id: str, interval: float | None = None,
                    timeout: float | None = None) -> dict[str, Any]:
    s = get_settings()
    interval = POLL_INTERVAL if interval is None else interval
    timeout = POLL_TIMEOUT if timeout is None else timeout
    waited = 0.0
    while True:
        _guard_image()  # switch flipped while a background job polls → stop sending requests
        try:
            r = await _request("GET", f"{s.dashscope_api_url}/tasks/{task_id}", headers=_headers())  # safe to retry
            data = _raise_for(r)
        except DashScopeError as e:
            if not e.retryable or waited >= timeout:  # 429/5xx while polling: keep polling the same task
                raise
            data = {"output": {"task_status": "RETRY"}}
        out = data.get("output") or {}
        status = out.get("task_status")
        if status == "SUCCEEDED":
            return out
        if status in ("FAILED", "CANCELED", "UNKNOWN"):
            raise DashScopeError(str(out.get("code") or status), str(out.get("message", "")))
        if waited >= timeout:
            raise DashScopeError("Timeout", f"task {task_id} still {status}", retryable=True)
        await asyncio.sleep(interval)
        waited += interval


def image_url_from(output: dict[str, Any]) -> str:
    for res in output.get("results") or []:
        if res.get("url"):
            return res["url"]
    for ch in output.get("choices") or []:  # wan2.6 protocol
        for c in (ch.get("message") or {}).get("content") or []:
            if c.get("image"):
                return c["image"]
    raise DashScopeError("NoImage", "task succeeded but returned no image url")


async def text_to_image(prompt: str, negative_prompt: str = "", size: str = "1280*720",
                        model: str | None = None, seed: int | None = None) -> bytes:
    """Full async-task flow: create → poll → download PNG bytes."""
    _guard_image()
    task_id = await create_image_task(prompt, negative_prompt, size, model, seed)
    out = await poll_task(task_id)
    _guard_image()
    return await _download(image_url_from(out))


async def text_to_speech(text: str, voice: str, model: str | None = None,
                         language_type: str = "Chinese") -> bytes:
    """Qwen-TTS non-streaming → WAV bytes. Retries once with qwen3-tts-flash on "Model not exist" (BUG-002)."""
    global _tts_model_override
    m = model or effective_tts_model()
    try:
        return await _tts_once(text, voice, m, language_type)
    except DashScopeError as e:
        if not _model_missing(e) or m == TTS_FALLBACK_MODEL:
            raise
        log.warning("tts model %s unavailable, retrying with %s", m, TTS_FALLBACK_MODEL)
        data = await _tts_once(text, voice, TTS_FALLBACK_MODEL, language_type)
        _tts_model_override = TTS_FALLBACK_MODEL
        return data


async def _tts_once(text: str, voice: str, model: str, language_type: str) -> bytes:
    s = get_settings()
    body = {"model": model, "input": {"text": text[:600], "voice": voice, "language_type": language_type}}
    r = await _request("POST", f"{s.dashscope_api_url}/services/aigc/multimodal-generation/generation",
                       headers=_headers(), json=body)  # billed: retried only if not sent
    data = _raise_for(r)
    audio = (data.get("output") or {}).get("audio") or {}
    if audio.get("url"):
        return await _download(audio["url"])
    if audio.get("data"):
        import base64
        return base64.b64decode(audio["data"])
    raise DashScopeError("NoAudio", "tts returned no audio")
