"""Embeddings: DashScope text-embedding-v3, or a deterministic local hash embedding (fallback)."""
from __future__ import annotations

import hashlib
import math
import re

from app.config import get_settings
from app.llm.client import embed_remote

_WORD = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


def tokens(text: str) -> list[str]:
    """Latin words + CJK unigrams/bigrams (good enough for lexical-semantic recall offline)."""
    toks = _WORD.findall(text.lower())
    cjk = [t for t in toks if len(t) == 1 and "\u4e00" <= t <= "\u9fff"]
    bigrams = [a + b for a, b in zip(cjk, cjk[1:])]
    return toks + bigrams * 2


def hash_embed(text: str, dim: int | None = None) -> list[float]:
    dim = dim or get_settings().embedding_dim
    v = [0.0] * dim
    for t in tokens(text):
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        v[h % dim] += 1.0 if (h >> 64) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


async def embed(texts: list[str]) -> tuple[list[list[float]], str]:
    """Returns (vectors, provider) where provider is 'dashscope' or 'hash'."""
    remote = await embed_remote(texts)
    if remote and len(remote) == len(texts):
        return remote, "dashscope"
    return [hash_embed(t) for t in texts], "hash"
