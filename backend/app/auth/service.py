"""用户、会话（refresh family）、统计与学习记录。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlmodel import col, func, select

from app.auth import security as sec
from app.auth.context import DEMO_ID
from app.auth.errors import AuthError
from app.auth.prefs import normalize
from app.db import (AssetRow, AuthSessionRow, EventRow, MemoryRow, RefreshTokenRow, ReportRow, TurnRow, UserRow,
                    WorldRow, session_scope, utcnow)


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


def user_out(u: UserRow) -> dict[str, Any]:
    return {"id": u.id, "username": u.username, "email": u.email, "nickname": u.nickname or u.username,
            "avatar_url": u.avatar_url, "bio": u.bio or "", "preferences": normalize(u.preferences),
            "is_demo": bool(u.is_demo), "created_at": _iso(u.created_at), "updated_at": _iso(u.updated_at),
            "last_login_at": _iso(u.last_login_at)}


def get_user(user_id: str) -> UserRow | None:
    with session_scope() as s:
        return s.get(UserRow, user_id)


def find_login(login: str) -> UserRow | None:
    v = login.strip().lower()
    with session_scope() as s:
        if "@" in v:
            return s.exec(select(UserRow).where(UserRow.email == v)).first()
        return s.exec(select(UserRow).where(UserRow.username_lower == v)).first()


def username_taken(name: str) -> bool:
    with session_scope() as s:
        return s.exec(select(UserRow.id).where(UserRow.username_lower == name.lower())).first() is not None


def email_taken(email: str, exclude: str | None = None) -> bool:
    with session_scope() as s:
        q = select(UserRow.id).where(UserRow.email == email)
        if exclude:
            q = q.where(UserRow.id != exclude)
        return s.exec(q).first() is not None


def demo_brief() -> dict[str, Any]:
    u = get_user(DEMO_ID)
    return {"id": DEMO_ID, "username": "demo", "nickname": (u.nickname if u else "演示账号")}


# ---------------------------------------------------------------- 会话
def _issue(s, u: UserRow, family: str, remember: bool) -> tuple[str, str]:  # noqa: ANN001
    jti = sec.new_jti()
    rttl = sec.refresh_ttl(remember)
    s.add(RefreshTokenRow(jti=jti, family_id=family, user_id=u.id, expires_at=utcnow() + rttl))
    access = sec.encode({"sub": u.id, "typ": "access", "ver": u.token_version, "fam": family}, sec.access_ttl())
    refresh = sec.encode({"sub": u.id, "typ": "refresh", "ver": u.token_version, "fam": family, "jti": jti,
                          "rem": bool(remember)}, rttl)
    return access, refresh


def start_session(u: UserRow, *, remember: bool = True, user_agent: str = "") -> tuple[str, str]:
    with session_scope() as s:
        fam = uuid.uuid4().hex
        s.add(AuthSessionRow(id=fam, user_id=u.id, remember=remember, user_agent=(user_agent or "")[:200]))
        row = s.get(UserRow, u.id)
        if row:
            row.last_login_at = utcnow()
            s.add(row)
        return _issue(s, u, fam, remember)


def revoke_family(family: str) -> None:
    with session_scope() as s:
        fam = s.get(AuthSessionRow, family)
        if fam and not fam.revoked_at:
            fam.revoked_at = utcnow()
            s.add(fam)
        for t in s.exec(select(RefreshTokenRow).where(RefreshTokenRow.family_id == family,
                                                      col(RefreshTokenRow.revoked_at).is_(None))).all():
            t.revoked_at = utcnow()
            s.add(t)


def revoke_all(user_id: str) -> None:
    with session_scope() as s:
        fams = s.exec(select(AuthSessionRow.id).where(AuthSessionRow.user_id == user_id,
                                                      col(AuthSessionRow.revoked_at).is_(None))).all()
    for f in fams:
        revoke_family(f)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def rotate(refresh_token: str | None) -> tuple[UserRow, str, str, bool]:
    """校验并轮换 refresh：返回 (user, access, refresh, remember)。重放已作废的 refresh → 吊销整串。"""
    bad = AuthError(401, "refresh_invalid", "登录已失效，请重新登录", clear_cookies=True)
    c = sec.decode(refresh_token or "", "refresh")
    if not c or not c.get("jti") or not c.get("fam"):
        raise bad
    with session_scope() as s:
        tok = s.get(RefreshTokenRow, c["jti"])
        fam = s.get(AuthSessionRow, c["fam"])
        u = s.get(UserRow, c["sub"])
        if not tok or not fam or not u or tok.family_id != fam.id or tok.user_id != u.id:
            raise bad
        reused = tok.revoked_at is not None or tok.replaced_by is not None
        if fam.revoked_at or c.get("ver") != u.token_version or _aware(tok.expires_at) < utcnow():
            raise bad
    if reused:
        revoke_family(c["fam"])  # 疑似被盗重放：整串吊销
        raise bad
    with session_scope() as s:
        tok = s.get(RefreshTokenRow, c["jti"])
        u = s.get(UserRow, c["sub"])
        remember = bool(c.get("rem", True))
        access, refresh = _issue(s, u, c["fam"], remember)
        tok.replaced_by = sec.decode(refresh, "refresh")["jti"]  # type: ignore[index]
        tok.revoked_at = utcnow()
        s.add(tok)
    return u, access, refresh, remember


def check_access(token: str) -> tuple[UserRow, str] | None:
    """合法 access → (user, family)。过期/伪造/会话已吊销/改过密码 → None。"""
    c = sec.decode(token, "access")
    if not c:
        return None
    with session_scope() as s:
        u = s.get(UserRow, c["sub"])
        fam = s.get(AuthSessionRow, c.get("fam") or "")
        if not u or c.get("ver") != u.token_version or not fam or fam.revoked_at or fam.user_id != u.id:
            return None
        return u, fam.id


# ---------------------------------------------------------------- 统计 / 学习记录
def _edu_record(r: WorldRow, turns: int) -> dict[str, Any]:
    d = r.data or {}
    flags = (d.get("state") or {}).get("flags") or {}
    edu = flags.get("edu") or {}
    summ = flags.get("edu_summary")
    return {"world_id": r.id, "title": r.title, "subject": edu.get("subject"), "grade": edu.get("grade"),
            "status": r.status, "turns": turns, "cards": len(d.get("knowledge_cards") or []),
            "created_at": _iso(r.created_at), "updated_at": _iso(r.updated_at),
            "summary": summ if isinstance(summ, dict) else None}


def _turn_counts(s, ids: list[str]) -> dict[str, int]:  # noqa: ANN001
    if not ids:
        return {}
    rows = s.exec(select(TurnRow.world_id, func.count()).where(col(TurnRow.world_id).in_(ids))
                  .group_by(TurnRow.world_id)).all()
    return {w: int(n) for w, n in rows}


def learning(owner: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    with session_scope() as s:
        base = select(WorldRow).where(WorldRow.owner_id == owner, WorldRow.mode == "education")
        total = s.exec(select(func.count()).select_from(base.subquery())).one()
        rows = s.exec(base.order_by(col(WorldRow.updated_at).desc()).offset(offset).limit(limit)).all()
        counts = _turn_counts(s, [r.id for r in rows])
        return {"items": [_edu_record(r, counts.get(r.id, 0)) for r in rows], "total": int(total),
                "limit": limit, "offset": offset}


def stats(owner: str) -> dict[str, Any]:
    from app.services.repo import iso

    with session_scope() as s:
        rows = s.exec(select(WorldRow).where(WorldRow.owner_id == owner).order_by(col(WorldRow.updated_at).desc())).all()
        ids = [r.id for r in rows]
        counts = _turn_counts(s, ids)
        edu = [r for r in rows if r.mode == "education"]

        def cnt(model, *conds) -> int:  # noqa: ANN001
            if not ids:
                return 0
            return int(s.exec(select(func.count()).select_from(model).where(col(model.world_id).in_(ids), *conds)).one())

        first = last = None
        if ids:
            first, last = s.exec(select(func.min(TurnRow.created_at), func.max(TurnRow.created_at))
                                 .where(col(TurnRow.world_id).in_(ids))).one()
        chapters = sum(int(((r.data or {}).get("state") or {}).get("chapter") or 0) for r in rows)
        reports = int(s.exec(select(func.count()).select_from(ReportRow).where(ReportRow.reporter_id == owner)).one())
        edu_summaries = sum(1 for r in edu if isinstance((((r.data or {}).get("state") or {}).get("flags") or {})
                                                         .get("edu_summary"), dict))
        recent = [{"id": r.id, "title": r.title, "genre": r.genre, "tone": r.tone, "mode": r.mode,
                   "turn": ((r.data or {}).get("state") or {}).get("turn", 0), "status": r.status,
                   "created_at": iso(r.created_at), "updated_at": iso(r.updated_at), "owner_id": r.owner_id}
                  for r in rows[:5]]
        return {
            "worlds": {"total": len(rows), "story": sum(r.mode == "story" for r in rows), "education": len(edu),
                       "draft": sum(r.status == "draft" for r in rows), "active": sum(r.status == "active" for r in rows),
                       "ended": sum(r.status == "ended" for r in rows),
                       "imported": sum((r.origin or "generated") == "imported" for r in rows)},
            "saves": {"slots": sum(r.status != "draft" for r in rows),
                      "imported": sum((r.origin or "generated") == "imported" for r in rows)},
            "play": {"turns": sum(counts.values()), "chapters": chapters,
                     "injected_events": cnt(EventRow, EventRow.type == "injected"),
                     "offscreen_events": cnt(EventRow, EventRow.type == "offscreen"),
                     "memories": cnt(MemoryRow), "first_played_at": _iso(first), "last_played_at": _iso(last)},
            "assets": {"image": cnt(AssetRow, AssetRow.type == "image"), "audio": cnt(AssetRow, AssetRow.type == "audio")},
            "learning": {"worlds": len(edu), "turns": sum(counts.get(r.id, 0) for r in edu),
                         "knowledge_cards": sum(len((r.data or {}).get("knowledge_cards") or []) for r in edu),
                         "summaries": edu_summaries,
                         "latest": _edu_record(edu[0], counts.get(edu[0].id, 0)) if edu else None},
            "reports_submitted": reports,
            "recent_worlds": recent,
        }
