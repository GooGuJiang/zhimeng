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
    owner_id: str | None = Field(default=None, index=True)  # v1.4：归属用户（子表经 world_id 继承）
    origin: str = "generated"                                # generated | imported
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
    # v1.3：原地升级（占位 → 真实文件、regenerate）时自动 +1 / 刷新（见下方 before_update 监听），前端据此刷新缓存
    version: int = 1
    updated_at: datetime | None = None


@event.listens_for(AssetRow, "before_update")
def _asset_bump(_mapper, _conn, target: AssetRow) -> None:  # noqa: ANN001
    """资产行的 url/source 变化（multimodal 的后台原地升级或 regenerate）→ version+1、updated_at=now。"""
    from sqlalchemy import inspect as sa_inspect
    st = sa_inspect(target)
    if st.attrs.url.history.has_changes() or st.attrs.source.history.has_changes():
        target.version = (target.version or 1) + 1
        target.updated_at = utcnow()


class ReportRow(SQLModel, table=True):
    __tablename__ = "reports"
    id: str = Field(primary_key=True)
    world_id: str | None = None
    turn_id: str | None = None
    content: str
    reason: str
    status: str = "received"
    reporter_id: str | None = None  # v1.4：举报人
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- v1.4 用户系统
class UserRow(SQLModel, table=True):
    __tablename__ = "users"
    id: str = Field(primary_key=True)
    username: str
    username_lower: str = Field(index=True, unique=True)
    email: str | None = Field(default=None, index=True, unique=True)  # 选填，存小写；NULL 可重复
    password_hash: str
    nickname: str = ""
    avatar_url: str | None = None
    bio: str = ""
    preferences: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    is_demo: bool = False
    token_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = None


class AuthSessionRow(SQLModel, table=True):
    """一次登录 = 一个 refresh family；登出/重放检测吊销整串（该会话的 access 也随之失效）。"""
    __tablename__ = "auth_sessions"
    id: str = Field(primary_key=True)  # family id
    user_id: str = Field(index=True)
    remember: bool = True
    user_agent: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    revoked_at: datetime | None = None


class RefreshTokenRow(SQLModel, table=True):
    __tablename__ = "refresh_tokens"
    jti: str = Field(primary_key=True)
    family_id: str = Field(index=True)
    user_id: str = Field(index=True)
    expires_at: datetime
    revoked_at: datetime | None = None
    replaced_by: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class AuthEventRow(SQLModel, table=True):
    """限流记录：login_fail / pwd_fail / register / refresh（按 key + 时间窗计数）。"""
    __tablename__ = "auth_events"
    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    key: str = Field(index=True)
    ip: str = Field(default="", index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)


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
_MIGRATIONS = {"turns": [("source", "VARCHAR DEFAULT 'llm'")],
               "assets": [("version", "INTEGER DEFAULT 1"), ("updated_at", "DATETIME")], "events": [("origin", "VARCHAR DEFAULT 'turn'")], "trajectories": [("origin", "VARCHAR DEFAULT 'turn'")],
               # v1.4 用户系统：数据归属
               "worlds": [("owner_id", "VARCHAR"), ("origin", "VARCHAR DEFAULT 'generated'")],
               "reports": [("reporter_id", "VARCHAR")]}


def _migrate(engine) -> None:  # noqa: ANN001
    from sqlalchemy import text
    with engine.begin() as conn:
        for table, cols in _MIGRATIONS.items():
            have = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, ddl in cols:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_worlds_owner_id ON worlds (owner_id)"))
    # v1.4：建 demo 账号；旧数据（owner_id 为空）归 u_demo
    from app.auth.bootstrap import bootstrap
    bootstrap(engine)


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
