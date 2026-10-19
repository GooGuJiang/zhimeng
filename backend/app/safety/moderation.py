"""LLM moderation client for F9 — fast path first, LLM only when it is worth it.

Why: in real-model mode the first token of a turn must arrive in ≤2 s, while a qwen-turbo moderation call takes
1.1–3.9 s and adds to 429 rate limiting. Strategy (also exposed via ``policy()["moderation"]``):

1. **Triage** (``triage``): for high-frequency contexts (``turn``, ``memory_query``, generated output) a text that
   the rule layer considers clean, short and unremarkable skips the LLM entirely. The LLM is only consulted for
   grey-zone hits (sensitive-but-not-forbidden words), injection-like wording, obfuscation, URLs/contacts,
   latin-heavy text, long text, crisis hints, over-rating hints or minor-mode sensitive topics.
   Low-frequency contexts (``world_prompt``, ``source_text``, ``inject``) always get an LLM look.
2. **Strict timeout** per context (turn/memory_query 1.5 s, output 3 s, low-frequency 5 s). On timeout the
   caller uses the rule-layer result; the in-flight call keeps running (bounded) and fills the cache.
3. **Cache**: LRU with TTL keyed by sha256(minor_mode|kind|text).
4. **Single-flight**: concurrent identical requests share one call.
5. **Rate control**: global concurrency cap + minimum spacing between call starts; fast contexts skip the LLM
   instead of queueing when saturated.
6. **429 back-off**: exponential cool-down (5 s → 10 s → … ≤120 s), reset on the next success; during the
   cool-down only the rule layer runs.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections import OrderedDict
from typing import Any

from app.safety import keywords as kw

log = logging.getLogger("zhimeng.safety")


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


FAST_CONTEXTS = {"turn", "memory_query"}
ALWAYS_CONTEXTS = {"world_prompt", "source_text", "inject"}
TIMEOUT_FAST = _f("ZM_MODERATION_TIMEOUT_FAST", 1.5)
TIMEOUT_OUTPUT = _f("ZM_MODERATION_TIMEOUT_OUTPUT", 3.0)
TIMEOUT_SLOW = _f("ZM_MODERATION_TIMEOUT", 5.0)
BACKGROUND_DEADLINE = _f("ZM_MODERATION_BG_DEADLINE", 8.0)  # hard cap for a call that outlived its waiter
SHORT_CHARS = {"turn": int(_f("ZM_MODERATION_SHORT_CHARS", 40)), "memory_query": 60}
MIN_CHARS = 6
MAX_CONCURRENCY = max(1, int(_f("ZM_MODERATION_CONCURRENCY", 2)))
MIN_INTERVAL = _f("ZM_MODERATION_MIN_INTERVAL", 0.2)
CACHE_TTL = _f("ZM_MODERATION_CACHE_TTL", 900)
CACHE_MAX = int(_f("ZM_MODERATION_CACHE_MAX", 2048))
BACKOFF_BASE = _f("ZM_MODERATION_COOLDOWN", 5.0)
BACKOFF_MAX = 120.0

STATS: dict[str, int] = {"llm_calls": 0, "cache_hits": 0, "dedup_joins": 0, "skipped_clean": 0, "skipped_busy": 0,
                         "skipped_cooldown": 0, "timeouts": 0, "rate_limited": 0, "errors": 0}


class TTLCache:
    def __init__(self, maxsize: int, ttl: float) -> None:
        self.maxsize, self.ttl = maxsize, ttl
        self._d: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        item = self._d.get(key)
        if item is None:
            return None
        exp, val = item
        if exp < time.monotonic():
            self._d.pop(key, None)
            return None
        self._d.move_to_end(key)
        return val

    def put(self, key: str, val: Any) -> None:
        self._d[key] = (time.monotonic() + self.ttl, val)
        self._d.move_to_end(key)
        while len(self._d) > self.maxsize:
            self._d.popitem(last=False)

    def clear(self) -> None:
        self._d.clear()

    def __len__(self) -> int:
        return len(self._d)


cache = TTLCache(CACHE_MAX, CACHE_TTL)
_inflight: dict[str, asyncio.Task] = {}
_active = 0
_next_start = 0.0
_cooldown_until = 0.0
_strikes = 0


def reset() -> None:
    """Testing / admin: clear cache, in-flight map, limiter and back-off state."""
    global _active, _next_start, _cooldown_until, _strikes
    cache.clear()
    _inflight.clear()
    for k in STATS:
        STATS[k] = 0
    _active, _next_start, _cooldown_until, _strikes = 0, 0.0, 0.0, 0


def timeout_for(context: str) -> float:
    if context in FAST_CONTEXTS:
        return TIMEOUT_FAST
    if context == "output":
        return TIMEOUT_OUTPUT
    return TIMEOUT_SLOW


def triage(text: str, *, context: str, minor_mode: bool = False, cap: str = "teen",
           keyword_rating: str = "all") -> list[str]:
    """Reasons to consult the LLM (empty list → rule layer alone is trusted)."""
    if context in ALWAYS_CONTEXTS:
        return [f"context:{context}"]
    t = text or ""
    n = kw.normalize(t)
    reasons: list[str] = []
    if context in SHORT_CHARS and len(n) > SHORT_CHARS[context]:
        reasons.append("long")
    if kw.crisis_hint(t):
        reasons.append("self_harm_hint")
    grey = kw.grey_hits(t, minor_mode)
    reasons += [f"grey:{c}" for c in sorted(grey)]
    if kw.injection_hint(t):
        reasons.append("injection_like")
    if kw.obfuscated(t):
        reasons.append("obfuscated")
    if kw.contact_or_url(t):
        reasons.append("contact_or_url")
    if context != "output" and kw.latin_heavy(t):
        reasons.append("latin_heavy")
    if keyword_rating == "mature":
        reasons.append("rating_mature")
    elif keyword_rating == "teen" and cap == "all":
        reasons.append("rating_over_cap")
    return reasons


def _key(text: str, minor_mode: bool, kind: str) -> str:
    return hashlib.sha256(f"{minor_mode}|{kind}|{text}".encode()).hexdigest()


def _rate_limited(msg: str) -> bool:
    m = msg.lower()
    return any(k in m for k in ("429", "limit_requests", "rate limit", "ratelimit", "throttl", "too many requests"))


def _note_429() -> None:
    global _cooldown_until, _strikes
    _strikes += 1
    STATS["rate_limited"] += 1
    _cooldown_until = time.monotonic() + min(BACKOFF_MAX, BACKOFF_BASE * (2 ** (_strikes - 1)))


def cooling() -> bool:
    return time.monotonic() < _cooldown_until


async def _call(prompt: str, key: str, model: str) -> dict[str, Any] | None:
    """One real moderation call (rate-limited, concurrency-capped). Fills the cache."""
    global _strikes
    from app.llm import client as llm

    try:
        STATS["llm_calls"] += 1
        errors_before = llm.STATS.get("errors", 0)
        data = await llm.chat_json([{"role": "user", "content": prompt}], model=model, temperature=0,
                                   max_tokens=200)
        if data is None:
            last = str(llm.STATS.get("last_error") or "")
            new_error = llm.STATS.get("errors", 0) > errors_before
            if new_error and _rate_limited(last):
                _note_429()
                return None
            if new_error and ("data_inspection" in last.lower() or "inappropriate" in last.lower()):
                v = {"verdict": "block", "categories": ["provider_moderation"], "crisis": False,
                     "rating": "mature", "reason": "平台内容安全拦截"}
                cache.put(key, v)
                return v
            STATS["errors"] += 1
            return None
        v = normalize_verdict(data)
        if v is not None:
            _strikes = 0
            cache.put(key, v)
        return v
    except Exception as e:  # noqa: BLE001
        STATS["errors"] += 1
        if _rate_limited(f"{type(e).__name__} {e}"):
            _note_429()
        log.info("moderation call failed: %s", type(e).__name__)
        return None


def normalize_verdict(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict) or "verdict" not in data:
        return None
    verdict_s = str(data.get("verdict", "allow")).lower()
    return {
        "verdict": verdict_s if verdict_s in {"allow", "flag", "block"} else "allow",
        "categories": [str(c) for c in (data.get("categories") or []) if c][:8],
        "crisis": data.get("crisis") is True or str(data.get("crisis")).lower() == "true",
        "rating": data.get("rating") if data.get("rating") in {"all", "teen", "mature"} else "all",
        "reason": str(data.get("reason", ""))[:200],
    }


async def moderate(text: str, prompt: str, *, minor_mode: bool, kind: str, context: str,
                   model: str, timeout: float | None = None) -> dict[str, Any] | None:
    """Cached, single-flight, rate-controlled moderation. Returns a verdict or None (→ rules only). Never raises."""
    global _next_start, _active
    key = _key(text, minor_mode, kind)
    hit = cache.get(key)
    if hit is not None:
        STATS["cache_hits"] += 1
        return hit
    if cooling():
        STATS["skipped_cooldown"] += 1
        return None
    timeout = timeout_for(context) if timeout is None else timeout
    loop = asyncio.get_running_loop()
    task = _inflight.get(key)
    if task is not None and not task.done() and task.get_loop() is loop:
        STATS["dedup_joins"] += 1
    else:
        # latency-critical waiters skip instead of queueing; background reviews (longer timeout) may wait
        fast = (context in FAST_CONTEXTS or context == "output") and timeout < TIMEOUT_SLOW
        if _active >= MAX_CONCURRENCY and fast:
            STATS["skipped_busy"] += 1
            return None
        now = time.monotonic()
        wait = max(0.0, _next_start - now)
        if fast and wait > timeout / 2:
            STATS["skipped_busy"] += 1
            return None
        _next_start = max(now, _next_start) + MIN_INTERVAL

        async def run() -> dict[str, Any] | None:
            if wait:
                await asyncio.sleep(wait)
            try:
                return await asyncio.wait_for(_call(prompt, key, model), timeout=max(timeout, BACKGROUND_DEADLINE))
            except asyncio.TimeoutError:
                return None

        task = loop.create_task(run())
        _inflight[key] = task
        _active += 1  # counted from creation (incl. spacing wait) so concurrent bursts see saturation

        def _done(t: asyncio.Task, k: str = key) -> None:
            global _active
            _active = max(0, _active - 1)
            if _inflight.get(k) is t:
                _inflight.pop(k, None)

        task.add_done_callback(_done)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except asyncio.TimeoutError:
        STATS["timeouts"] += 1
        return None
    except Exception:  # noqa: BLE001
        return None


def describe() -> dict[str, Any]:
    """Strategy summary for ``policy()``."""
    return {
        "strategy": "规则层优先：高频场景（回合输入/记忆提问/生成文本）规则层干净且无可疑特征时直接放行，不调用大模型；"
                    "可疑（灰区词、疑似注入、变形/混淆、链接联系方式、长文本、危机暗示、超分级、未成年人敏感话题）才调用大模型；"
                    "低频场景（世界设定/课文史料/上帝插入事件）始终调用。",
        "always_llm_contexts": sorted(ALWAYS_CONTEXTS),
        "fast_contexts": sorted(FAST_CONTEXTS) + ["output"],
        "short_chars": SHORT_CHARS,
        "timeouts_s": {"turn": TIMEOUT_FAST, "memory_query": TIMEOUT_FAST, "output": TIMEOUT_OUTPUT,
                       "world_prompt/source_text/inject": TIMEOUT_SLOW},
        "on_timeout": "按规则层结果处理（不放行规则层已拦截的内容）",
        "cache": {"type": "LRU+TTL", "ttl_s": CACHE_TTL, "max": CACHE_MAX, "key": "sha256(minor_mode|kind|text)"},
        "single_flight": True,
        "rate_control": {"max_concurrency": MAX_CONCURRENCY, "min_interval_s": MIN_INTERVAL,
                         "fast_contexts_when_saturated": "跳过大模型，仅规则层"},
        "rate_limit_backoff": {"base_s": BACKOFF_BASE, "max_s": BACKOFF_MAX, "mode": "exponential, reset on success"},
        "stats": dict(STATS),
    }
