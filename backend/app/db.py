"""SQLite persistence (SQLModel). Structured world state lives here; vectors live in Chroma."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, event
from sqlmodel import Field, Session, SQLModel, create_engine

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorldRow(SQLModel, table=True):
    __tablename__ = "worlds"
    id: str = Field(primary_key=True)
    title: str
    genre: str = ""
    tone: str = ""
    mode: str = "story"
    status: str = "draft"
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))  # full World JSON
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CharacterRow(SQLModel, table=True):
    """Structured mirror of characters (queryable state table, F4)."""
    __tablename__ = "characters"
    id: str = Field(primary_key=True)
    world_id: str = Field(index=True, primary_key=True)
    name: str
    persona: str = ""
    goals: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    relations: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    location_id: str | None = None
    mood: str = ""
    status: str = ""


class TurnRow(SQLModel, table=True):
    __tablename__ = "turns"
    id: str = Field(primary_key=True)
    world_id: str = Field(index=True)
    index: int
    chapter: int
    action: str
    narration: str
    options: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    facts: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    event_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    asset_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    key_scene: bool = False
    source: str = "llm"  # 旁白来源 llm | fallback
    client_turn_id: str | None = Field(default=None, index=True)
    state_before: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))  # snapshot for retry
    created_at: datetime = Field(default_factory=utcnow)


class EventRow(SQLModel, table=True):
    __tablename__ = "events"
    id: str = Field(primary_key=True)
    world_id: str = Field(index=True)
    type: str
    summary: str
    actor_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    location_id: str | None = None
    turn: int = 0
    chapter: int = 1
    impact: str = "low"
    in_world_time: str = ""
    seen: bool = False
    consumed: bool = False  # injected events: woven into narration yet?
    origin: str = "turn"    # turn | tick（上帝视角手动推进，独立于回合重试保留）| god
    timestamp: datetime = Field(default_factory=utcnow)


class MemoryRow(SQLModel, table=True):
    __tablename__ = "memories"
    id: str = Field(primary_key=True)
    world_id: str = Field(index=True)
    kind: str  # fact|event|summary|injected|setting|npc
    content: str
    turn: int = 0
    chapter: int = 1
    refs: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class SummaryRow(SQLModel, table=True):
    __tablename__ = "summaries"
    id: str = Field(primary_key=True)
    world_id: str = Field(index=True)
    chapter: int
    from_turn: int
    to_turn: int
    summary: str
    created_at: datetime = Field(default_factory=utcnow)


class TrajectoryRow(SQLModel, table=True):
    __tablename__ = "trajectories"
    id: str = Field(primary_key=True)
    world_id: str = Field(index=True)
    character_id: str = Field(index=True)
    turn: int
    location_id: str | None = None
    action: str
    mood: str = ""
    origin: str = "turn"
    timestamp: datetime = Field(default_factory=utcnow)


class AssetRow(SQLModel, table=True):
    __tablename__ = "assets"
    id: str = Field(primary_key=True)
    world_id: str = Field(index=True)
    type: str  # image|audio
    url: str
    turn_id: str | None = None
    prompt: str = ""
    cache_key: str = Field(index=True)
    source: str = "fallback"
    created_at: datetime = Field(default_factory=utcnow)


class ReportRow(SQLModel, table=True):
    __tablename__ = "reports"
    id: str = Field(primary_key=True)
    world_id: str | None = None
    turn_id: str | None = None
    content: str
    reason: str
    status: str = "received"
    created_at: datetime = Field(default_factory=utcnow)


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_engine(s.db_url, connect_args={"check_same_thread": False})

        @event.listens_for(_engine, "connect")
        def _pragma(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

        SQLModel.metadata.create_all(_engine)
        _migrate(_engine)
    return _engine


# 轻量迁移：给旧库补新增列（SQLite create_all 不会改已有表）
_MIGRATIONS = {"turns": [("source", "VARCHAR DEFAULT 'llm'")], "events": [("origin", "VARCHAR DEFAULT 'turn'")], "trajectories": [("origin", "VARCHAR DEFAULT 'turn'")]}


def _migrate(engine) -> None:  # noqa: ANN001
    from sqlalchemy import text
    with engine.begin() as conn:
        for table, cols in _MIGRATIONS.items():
            have = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, ddl in cols:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def reset_engine() -> None:
    global _engine
    _engine = None


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
