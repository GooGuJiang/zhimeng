"""World memory (F4): structured facts in SQLite + semantic vectors in local persistent ChromaDB.

Each memory has source refs (turn, chapter). Vectors are stored per embedding provider
(collection ``mem_dashscope`` / ``mem_hash``) and lazily back-filled from SQLite if a world was
written while the other provider was active.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlmodel import col, delete, select

from app.config import get_settings
from app.db import MemoryRow, session_scope
from app.memory.embeddings import embed, hash_embed, tokens
from app.schemas import Citation, MemoryItem

log = logging.getLogger("zhimeng.memory")
_chroma: Any = None
_chroma_failed = False


def chroma():
    """本地持久化 ChromaDB；导入或初始化失败时返回 None → 退化为 SQLite 全表 + 本地哈希向量检索。"""
    global _chroma, _chroma_failed
    if _chroma is None and not _chroma_failed:
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            _chroma = chromadb.PersistentClient(path=str(get_settings().chroma_dir),
                                                settings=ChromaSettings(anonymized_telemetry=False))
        except Exception as e:  # noqa: BLE001
            _chroma_failed = True
            log.warning("ChromaDB unavailable, using local fallback retrieval: %s", e)
    return _chroma


def chroma_status() -> str:
    return "chroma" if chroma() is not None else "local"


def reset_chroma() -> None:
    global _chroma, _chroma_failed
    _chroma, _chroma_failed = None, False


def _collection(provider: str):
    c = chroma()
    if c is None:
        raise RuntimeError("chroma unavailable")
    return c.get_or_create_collection(f"mem_{provider}", embedding_function=None,
                                      metadata={"hnsw:space": "cosine"})


def source_label(turn: int, chapter: int, kind: str) -> str:
    if turn <= 0:
        return "世界设定" if kind == "setting" else f"第{chapter}章·开局"
    return f"第{chapter}章·第{turn}回合"


def to_item(r: MemoryRow) -> MemoryItem:
    return MemoryItem(id=r.id, content=r.content, kind=r.kind, turn=r.turn, chapter=r.chapter,
                      source=source_label(r.turn, r.chapter, r.kind), created_at=r.created_at.isoformat())


async def add_memories(world_id: str, entries: list[dict[str, Any]]) -> list[str]:
    """entries: {content, kind, turn, chapter, refs?}. Returns memory ids."""
    entries = [e for e in entries if (e.get("content") or "").strip()]
    if not entries:
        return []
    rows = [MemoryRow(id=f"m_{uuid.uuid4().hex[:12]}", world_id=world_id, kind=e.get("kind", "fact"),
                      content=e["content"].strip(), turn=int(e.get("turn", 0)), chapter=int(e.get("chapter", 1)),
                      refs=e.get("refs") or {}) for e in entries]
    with session_scope() as s:
        s.add_all(rows)
    await _index(world_id, rows)
    return [r.id for r in rows]


async def _index(world_id: str, rows: list[MemoryRow]) -> str:
    vecs, provider = await embed([r.content for r in rows])
    try:
        _collection(provider).upsert(
            ids=[r.id for r in rows], embeddings=vecs, documents=[r.content for r in rows],
            metadatas=[{"world_id": world_id, "kind": r.kind, "turn": r.turn, "chapter": r.chapter} for r in rows])
    except Exception as e:  # noqa: BLE001
        log.warning("chroma upsert failed: %s", e)
    return provider


def list_memories(world_id: str, kind: str | None = None, limit: int = 100) -> list[MemoryRow]:
    with session_scope() as s:
        q = select(MemoryRow).where(MemoryRow.world_id == world_id)
        if kind:
            q = q.where(MemoryRow.kind == kind)
        return list(s.exec(q.order_by(col(MemoryRow.turn).desc(), col(MemoryRow.created_at).desc()).limit(limit)).all())


def delete_from_turn(world_id: str, turn: int) -> None:
    """Remove memories created at/after ``turn`` (used when retrying the last turn).
    上帝视角注入（kind=injected）是用户干预的留痕，重试时保留。"""
    with session_scope() as s:
        ids = [r.id for r in s.exec(select(MemoryRow).where(MemoryRow.world_id == world_id, MemoryRow.turn >= turn,
                                                            MemoryRow.kind != "injected"))]
        s.exec(delete(MemoryRow).where(col(MemoryRow.id).in_(ids)))  # type: ignore[call-overload]
    for p in ("hash", "dashscope"):
        try:
            if ids:
                _collection(p).delete(ids=ids)
        except Exception:  # noqa: BLE001
            pass


def delete_world(world_id: str) -> None:
    with session_scope() as s:
        s.exec(delete(MemoryRow).where(MemoryRow.world_id == world_id))  # type: ignore[call-overload]
    for p in ("hash", "dashscope"):
        try:
            _collection(p).delete(where={"world_id": world_id})
        except Exception:  # noqa: BLE001
            pass


def _lexical(query: str, text: str) -> float:
    q, t = set(tokens(query)), set(tokens(text))
    return len(q & t) / (len(q) or 1)


async def search(world_id: str, query: str, top_k: int = 5, kinds: list[str] | None = None,
                 before_turn: int | None = None) -> list[Citation]:
    """Hybrid retrieval: Chroma vector similarity + lexical overlap over the structured table.
    ``before_turn``：只检索该回合之前的记忆（重试最后一回合时排除旧版本）。"""
    rows = {r.id: r for r in list_memories(world_id, limit=5000)
            if before_turn is None or r.turn < before_turn or r.kind == "injected"}
    if not rows:
        return []
    vecs, provider = await embed([query])
    scores: dict[str, float] = {}
    try:
        coll = _collection(provider)
        indexed = coll.get(where={"world_id": world_id}, include=[])["ids"]
        missing = [rows[i] for i in rows if i not in set(indexed)]
        if missing:  # back-fill (provider switched, or index lost)
            await _index(world_id, missing)
        res = coll.query(query_embeddings=vecs, n_results=min(max(top_k * 3, 10), len(rows)),
                         where={"world_id": world_id})
        for mid, dist in zip(res["ids"][0], res["distances"][0]):
            scores[mid] = max(0.0, 1.0 - float(dist))
    except Exception as e:  # noqa: BLE001
        log.warning("chroma query failed, lexical only: %s", e)
        qv = hash_embed(query)
        for mid, r in rows.items():
            scores[mid] = sum(a * b for a, b in zip(qv, hash_embed(r.content)))
    out: list[Citation] = []
    for mid, r in rows.items():
        if kinds and r.kind not in kinds:
            continue
        sc = 0.6 * scores.get(mid, 0.0) + 0.4 * _lexical(query, r.content)
        out.append(Citation(fact_id=mid, content=r.content, turn=r.turn, chapter=r.chapter, kind=r.kind,
                            score=round(sc, 4), source=source_label(r.turn, r.chapter, r.kind)))
    out.sort(key=lambda c: c.score, reverse=True)
    return [c for c in out[:top_k] if c.score > 0]
