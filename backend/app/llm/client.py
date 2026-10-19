"""DashScope (Alibaba Bailian) access via the OpenAI-compatible endpoint, with graceful fallback.

Every function returns ``None`` (or raises ``LLMUnavailable`` for streams) when the key is
missing or the API fails, so callers can switch to local templates (SRS 5.3).
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings

log = logging.getLogger("zhimeng.llm")
_client: AsyncOpenAI | None = None
STATS: dict[str, Any] = {"calls": 0, "errors": 0, "last_error": None}


class LLMUnavailable(RuntimeError):
    """Raised when the remote model cannot be used (no key / API error / moderation)."""


def llm_enabled() -> bool:
    return get_settings().llm_enabled


def get_client() -> AsyncOpenAI:
    global _client
    s = get_settings()
    if _client is None:
        _client = AsyncOpenAI(api_key=s.dashscope_api_key, base_url=s.dashscope_base_url,
                              timeout=s.llm_timeout, max_retries=0)
    return _client


def _record_error(e: Exception) -> None:
    STATS["errors"] += 1
    STATS["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    log.warning("LLM error: %s", STATS["last_error"])


def parse_json(text: str) -> dict[str, Any] | None:
    """Parse a JSON object out of a model reply (tolerates ```json fences / prose)."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else {"items": v}
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


async def chat_text(messages: list[dict[str, str]], model: str | None = None,
                    temperature: float = 0.8, max_tokens: int = 1500, json_mode: bool = False) -> str | None:
    s = get_settings()
    if not s.llm_enabled:
        return None
    kwargs: dict[str, Any] = {"model": model or s.chat_model, "messages": messages,
                              "temperature": temperature, "max_tokens": max_tokens}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    for attempt in range(s.llm_retries + 1):
        try:
            STATS["calls"] += 1
            r = await get_client().chat.completions.create(**kwargs)
            return r.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001 - any API failure → fallback
            _record_error(e)
            if "data_inspection_failed" in str(e) or "inappropriate" in str(e).lower():
                return None  # provider moderation: do not retry
    return None


async def chat_json(messages: list[dict[str, str]], model: str | None = None,
                    temperature: float = 0.7, max_tokens: int = 3000) -> dict[str, Any] | None:
    text = await chat_text(messages, model, temperature, max_tokens, json_mode=True)
    data = parse_json(text or "")
    if text and data is None:
        STATS["last_error"] = "invalid JSON from model"
    return data


async def chat_stream(messages: list[dict[str, str]], model: str | None = None,
                      temperature: float = 0.85, max_tokens: int = 1200) -> AsyncIterator[str]:
    s = get_settings()
    if not s.llm_enabled:
        raise LLMUnavailable("no api key")
    try:
        STATS["calls"] += 1
        stream = await get_client().chat.completions.create(
            model=model or s.chat_model, messages=messages, temperature=temperature,
            max_tokens=max_tokens, stream=True)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except LLMUnavailable:
        raise
    except Exception as e:  # noqa: BLE001
        _record_error(e)
        raise LLMUnavailable(str(e)) from e


async def embed_remote(texts: list[str]) -> list[list[float]] | None:
    s = get_settings()
    if not s.llm_enabled or not texts:
        return None
    try:
        out: list[list[float]] = []
        for i in range(0, len(texts), 10):  # text-embedding-v3 batch limit = 10
            STATS["calls"] += 1
            r = await get_client().embeddings.create(model=s.embedding_model, input=texts[i:i + 10],
                                                     dimensions=s.embedding_dim, encoding_format="float")
            out.extend(d.embedding for d in r.data)
        return out
    except Exception as e:  # noqa: BLE001
        _record_error(e)
        return None
