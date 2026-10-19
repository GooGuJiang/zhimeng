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


class DashScopeError(RuntimeError):
    def __init__(self, code: str, message: str = "", retryable: bool = False):
        super().__init__(redact(f"{code}: {message[:200]}"))
        self.code = code
        self.retryable = retryable


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
CONNECT_RETRIES = int(os.getenv("ZM_MM_CONNECT_RETRIES", "2"))


def _client() -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(timeout=httpx.Timeout(s.llm_timeout, connect=CONNECT_TIMEOUT))


async def _request(client: httpx.AsyncClient, method: str, url: str, **kw: Any) -> httpx.Response:
    """Send with retries on *connection* failures only (request never reached the server → not billed,
    safe to repeat). Read timeouts / HTTP errors are not retried here."""
    for attempt in range(CONNECT_RETRIES + 1):
        try:
            return await client.request(method, url, **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            if attempt >= CONNECT_RETRIES:
                raise
            log.info("connect failed (%s), retry %d", type(e).__name__, attempt + 1)
            await asyncio.sleep(0.5 * (attempt + 1))
    raise AssertionError("unreachable")


def _https_first(url: str) -> list[str]:
    """Result URLs (OSS, signed) are sometimes plain http:// — many networks block port 80, and OSS serves the
    same signed URL over https (the signature does not cover the scheme). Try https first, then the original."""
    u = httpx.URL(url)
    if u.scheme == "http" and u.host.endswith(".aliyuncs.com"):
        return [str(u.copy_with(scheme="https")), url]
    return [url]


async def _download(client: httpx.AsyncClient, url: str) -> bytes:
    last: Exception | None = None
    for candidate in _https_first(url):
        try:
            r = await _request(client, "GET", candidate)  # result URLs: never send the Authorization header
            r.raise_for_status()
            return r.content
        except (httpx.HTTPError,) as e:
            last = e
    raise DashScopeError("DownloadFailed", f"{type(last).__name__}: {last}")


# Overridable for tests (avoid real sleeps).
POLL_INTERVAL = 2.0
POLL_TIMEOUT = 90.0


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
                             retryable=resp.status_code in (429, 500, 502, 503, 504) and code not in NON_RETRYABLE)
    return data


async def create_image_task(client: httpx.AsyncClient, prompt: str, negative_prompt: str = "",
                            size: str = "1280*720", model: str | None = None, seed: int | None = None) -> str:
    s = get_settings()
    params: dict[str, Any] = {"size": size, "n": 1, "prompt_extend": False, "watermark": WATERMARK}
    if seed is not None:
        params["seed"] = seed
    body = {"model": model or s.image_model,
            "input": {"prompt": prompt[:500], "negative_prompt": negative_prompt[:500]},
            "parameters": params}
    r = await _request(client, "POST", f"{s.dashscope_api_url}/services/aigc/text2image/image-synthesis",
                       headers=_headers(async_task=True), json=body)
    data = _raise_for(r)
    task_id = (data.get("output") or {}).get("task_id")
    if not task_id:
        raise DashScopeError("NoTaskId", str(data)[:200])
    return task_id


async def poll_task(client: httpx.AsyncClient, task_id: str, interval: float | None = None,
                    timeout: float | None = None) -> dict[str, Any]:
    s = get_settings()
    interval = POLL_INTERVAL if interval is None else interval
    timeout = POLL_TIMEOUT if timeout is None else timeout
    waited = 0.0
    while True:
        r = await _request(client, "GET", f"{s.dashscope_api_url}/tasks/{task_id}", headers=_headers())
        data = _raise_for(r)
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
    async with _client() as client:
        task_id = await create_image_task(client, prompt, negative_prompt, size, model, seed)
        out = await poll_task(client, task_id)
        url = image_url_from(out)
        return await _download(client, url)


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
    async with _client() as client:
        r = await _request(client, "POST", f"{s.dashscope_api_url}/services/aigc/multimodal-generation/generation",
                           headers=_headers(), json=body)
        data = _raise_for(r)
        audio = (data.get("output") or {}).get("audio") or {}
        if audio.get("url"):
            return await _download(client, audio["url"])
        if audio.get("data"):
            import base64
            return base64.b64decode(audio["data"])
        raise DashScopeError("NoAudio", "tts returned no audio")
