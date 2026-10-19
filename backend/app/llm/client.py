"""DashScope (Alibaba Bailian) access via the OpenAI-compatible endpoint, with graceful fallback.

- 备用模型链：主模型遇到 429/限流、连接断开、超时、5xx、模型不存在/无权限时，按 ``config`` 中的链自动切换
  （如 qwen-plus → qwen-plus-latest → qwen-max → qwen-turbo → qwen-flash）；出错的模型进入短暂冷却。
- 整条链都失败才返回 ``None`` / 抛 ``LLMUnavailable``，由调用方切到本地模板（SRS 5.3）。
- 内容审核类错误（data_inspection_failed）不切换模型、不重试。
- 绝不记录/输出 API key。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import get_settings

log = logging.getLogger("zhimeng.llm")
_client: AsyncOpenAI | None = None
STATS: dict[str, Any] = {"calls": 0, "errors": 0, "switches": 0, "last_error": None, "last_model": None,
                         "by_model": {}}
_cooldown: dict[str, float] = {}
_strikes: dict[str, int] = {}


class LLMUnavailable(RuntimeError):
    """Raised when the remote model cannot be used (no key / API error / moderation)."""


def llm_enabled() -> bool:
    return get_settings().llm_enabled


def get_client() -> AsyncOpenAI:
    global _client
    s = get_settings()
    if _client is None:
        # 实测：复用的长连接常被对端静默关闭（Server disconnected / incomplete chunked read），故不保活
        _client = AsyncOpenAI(api_key=s.dashscope_api_key, base_url=s.dashscope_base_url,
                              timeout=s.llm_timeout, max_retries=0,
                              http_client=httpx.AsyncClient(timeout=s.llm_timeout,
                                                            limits=httpx.Limits(max_keepalive_connections=0)))
    return _client


def _split(v: str) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def model_chain(model: str | None = None) -> list[str]:
    """主模型 + 其所在链上的后续备用模型（主模型不在任何链上时，接 chat 链）。冷却中的模型排到末尾。"""
    s = get_settings()
    primary = model or s.chat_model
    chains = [_split(s.skeleton_model_chain), _split(s.chat_model_chain), _split(s.fast_model_chain)]
    if primary == s.fast_model:
        chains = [chains[2], chains[1]]
    elif primary == s.skeleton_model:
        chains = [chains[0], chains[2]]
    else:
        chains = [chains[1], chains[2]]
    seq: list[str] = [primary]
    for ch in chains:
        if primary in ch:
            ch = ch[ch.index(primary) + 1:] + ch[:ch.index(primary)]
        seq += [m for m in ch if m not in seq]
        if primary in seq[1:] or len(seq) > 1:
            break
    now = time.monotonic()
    ready = [m for m in seq if _cooldown.get(m, 0) <= now]
    cooling = [m for m in seq if _cooldown.get(m, 0) > now]
    return ready + cooling


class _Attempts:
    """依次产出要尝试的模型；上一次是网络层断开（``conn=True``）时，同一模型先再试 ``llm_retries`` 次。每次调用独立一份状态。"""

    def __init__(self, primary: str) -> None:
        self.primary, self.conn = primary, False

    def __iter__(self):
        retries = max(0, get_settings().llm_retries)
        for m in model_chain(self.primary):
            self.conn = False
            yield m
            n = 0
            while self.conn and n < retries:
                self.conn = False
                n += 1
                yield m


def _kind(e: Exception) -> str:
    """switch：换模型重试；stop：不重试（审核拦截/请求本身有误）。"""
    t = f"{type(e).__name__} {e}".lower()
    if "data_inspection_failed" in t or "inappropriate" in t:
        return "stop"
    code = getattr(e, "status_code", None)
    if code in (400, 401) and "model" not in t:
        return "stop"
    return "switch"  # 429 / 403 / 404(model) / 5xx / 连接断开 / 超时


def _is_conn(e: Exception) -> bool:
    """网络层断开/超时：与模型本身无关 → 同模型先重试，不进入冷却。"""
    t = f"{type(e).__name__} {e}".lower()
    return getattr(e, "status_code", None) is None and any(
        k in t for k in ("connection", "disconnected", "timeout", "timed out", "chunked", "protocol"))


def _record_error(model: str, e: Exception) -> None:
    STATS["errors"] += 1
    STATS["last_error"] = f"{model}: {type(e).__name__}: {str(e)[:160]}"
    m = STATS["by_model"].setdefault(model, {"ok": 0, "err": 0})
    m["err"] += 1
    if not _is_conn(e):  # 连续失败指数退避（30s→60s→…≤8x），避免反复撞 429 的模型
        n = _strikes[model] = _strikes.get(model, 0) + 1
        _cooldown[model] = time.monotonic() + get_settings().model_cooldown_s * min(8, 2 ** (n - 1))
    log.warning("LLM error (%s): %s", model, STATS["last_error"])


def _record_ok(model: str, primary: str) -> None:
    STATS["last_model"] = model
    STATS["by_model"].setdefault(model, {"ok": 0, "err": 0})["ok"] += 1
    _cooldown.pop(model, None)
    _strikes.pop(model, None)
    if model != primary:
        STATS["switches"] += 1
        log.info("LLM switched %s → %s", primary, model)


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
                    temperature: float = 0.8, max_tokens: int = 1500, json_mode: bool = False,
                    meta: dict[str, Any] | None = None) -> str | None:
    """非流式调用；按备用模型链切换。``meta`` 可回传实际使用的模型。"""
    s = get_settings()
    if not s.llm_enabled:
        return None
    primary = model or s.chat_model
    att = _Attempts(primary)
    for m in att:
        kwargs: dict[str, Any] = {"model": m, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            STATS["calls"] += 1
            r = await get_client().chat.completions.create(**kwargs)
            _record_ok(m, primary)
            if meta is not None:
                meta["model"] = m
            return r.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001 - any API failure → next model / fallback
            _record_error(m, e)
            if _kind(e) == "stop":
                return None
            att.conn = _is_conn(e)
            await asyncio.sleep(0.2)
    return None


async def chat_json(messages: list[dict[str, str]], model: str | None = None,
                    temperature: float = 0.7, max_tokens: int = 3000,
                    meta: dict[str, Any] | None = None) -> dict[str, Any] | None:
    text = await chat_text(messages, model, temperature, max_tokens, json_mode=True, meta=meta)
    data = parse_json(text or "")
    if text and data is None:
        STATS["last_error"] = "invalid JSON from model"
    return data


async def chat_stream(messages: list[dict[str, str]], model: str | None = None,
                      temperature: float = 0.85, max_tokens: int = 1200,
                      meta: dict[str, Any] | None = None) -> AsyncIterator[str]:
    """流式调用。首字之前失败 → 切换下一个模型；已输出内容后断开 → 抛 LLMUnavailable（调用方决定兜底/重试）。"""
    s = get_settings()
    if not s.llm_enabled:
        raise LLMUnavailable("no api key")
    primary = model or s.chat_model
    last: Exception | None = None
    att = _Attempts(primary)
    for m in att:
        got = False
        try:
            STATS["calls"] += 1
            stream = await get_client().chat.completions.create(
                model=m, messages=messages, temperature=temperature, max_tokens=max_tokens, stream=True)
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    if not got:
                        got = True
                        _record_ok(m, primary)
                        if meta is not None:
                            meta["model"] = m
                    yield chunk.choices[0].delta.content
            if got:
                return
            raise RuntimeError("empty stream")
        except Exception as e:  # noqa: BLE001
            _record_error(m, e)
            last = e
            if got or _kind(e) == "stop":
                raise LLMUnavailable(str(e)) from e
            att.conn = _is_conn(e)
            await asyncio.sleep(0.2)
    raise LLMUnavailable(str(last) if last else "all models failed")


_RESUME = "（网络中断）请从上文最后一个字符之后无缝续写剩余部分，不要重复已输出内容，不要任何说明。"


async def chat_stream_resumable(messages: list[dict[str, str]], *, attempts: int = 5,
                                **kw: Any) -> AsyncIterator[str]:
    """可续写的流：首字后断流时把已输出部分作为 assistant 消息、请模型从断点续写（最多 ``attempts-1`` 次续写）。
    首字前整条模型链都失败 → 抛 LLMUnavailable（调用方走兜底）；续写次数用尽 → 抛 LLMUnavailable。"""
    sent = ""
    for i in range(attempts):
        cur = messages if not sent else messages + [{"role": "assistant", "content": sent},
                                                    {"role": "user", "content": _RESUME}]
        try:
            async for chunk in chat_stream(cur, **kw):
                sent += chunk
                yield chunk
            return
        except LLMUnavailable:
            if not sent or i == attempts - 1:
                raise
            log.warning("stream broke after %d chars → resuming (%d/%d)", len(sent), i + 1, attempts - 1)


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
        _record_error(s.embedding_model, e)
        return None


def stats() -> dict[str, Any]:
    now = time.monotonic()
    return {**{k: v for k, v in STATS.items() if k != "by_model"}, "by_model": STATS["by_model"],
            "cooling": sorted(m for m, t in _cooldown.items() if t > now)}
