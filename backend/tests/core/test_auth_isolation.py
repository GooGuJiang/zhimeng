"""v1.4 用户系统：数据归属与隔离、ZM_AUTH_REQUIRED 双模式、旧数据迁移、偏好下限、统计与学习记录。"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import stat

import pytest

from auth_helpers import PW, make_world, new_client, register, setenv, user_client
from test_core import first, sse


def code(r):
    return r.json().get("code")


@pytest.fixture
def two_users(core_env):
    a, b = user_client(), user_client()
    with a, b:
        yield a, b


def test_worlds_isolated_404(two_users):
    a, b = two_users
    w = make_world(a)
    wid = w["id"]
    assert w["owner_id"] == a.zm_user["id"] and w["origin"] == "generated"
    a.post(f"/api/worlds/{wid}/confirm")
    ev = sse(a, f"/api/worlds/{wid}/turns", {"action": "我去码头找线人"})
    assert first(ev, "done")["turn"]["index"] == 1
    assert [x["id"] for x in a.get("/api/worlds").json()] == [wid]
    assert b.get("/api/worlds").json() == []
    asset = a.post(f"/api/worlds/{wid}/assets/illustration", json={"prompt": "雨夜码头"}).json()
    probes = [("get", f"/api/worlds/{wid}"), ("get", f"/api/worlds/{wid}/turns"), ("get", f"/api/worlds/{wid}/events"),
              ("get", f"/api/worlds/{wid}/memory"), ("get", f"/api/worlds/{wid}/ui"), ("get", f"/api/worlds/{wid}/export"),
              ("get", f"/api/worlds/{wid}/poster"), ("get", f"/api/worlds/{wid}/god/npcs"),
              ("get", f"/api/worlds/{wid}/assets"), ("get", f"/api/assets/{asset['id']}"),
              ("get", f"/api/worlds/{wid}/education/summary"), ("get", f"/api/reports?world_id={wid}"),
              ("post", f"/api/worlds/{wid}/god/inject"), ("post", f"/api/worlds/{wid}/god/tick"),
              ("post", f"/api/assets/{asset['id']}/regenerate"), ("post", f"/api/worlds/{wid}/memory/query"),
              ("patch", f"/api/worlds/{wid}/settings"), ("post", f"/api/worlds/{wid}/confirm"),
              ("post", f"/api/worlds/{wid}/turns"), ("post", f"/api/worlds/{wid}/turns/retry"),
              ("post", f"/api/worlds/{wid}/regenerate"), ("post", f"/api/worlds/{wid}/ui/stream"),
              ("delete", f"/api/worlds/{wid}")]
    bodies = {"inject": {"content": "码头突发大火"}, "query": {"question": "线人叫什么"}, "turns": {"action": "我去偷看"},
              "settings": {"minor_mode": True}}
    for method, path in probes:
        body = next((v for k, v in bodies.items() if path.endswith(k)), None)
        kw = {"json": body} if method in ("post", "patch") else {}
        r = getattr(b, method)(path, **kw)
        assert r.status_code == 404 and code(r) == "not_found", f"{method} {path}: {r.status_code} {r.text[:120]}"
    assert b.post("/api/reports", json={"world_id": wid, "content": "x", "reason": "y"}).status_code == 404
    assert a.get(f"/api/worlds/{wid}").status_code == 200  # A 的世界完好


def test_import_owned_by_importer(two_users):
    a, b = two_users
    wid = make_world(a)["id"]
    save = a.get(f"/api/worlds/{wid}/export").json()
    w = b.post("/api/worlds/import", json=save).json()
    assert w["owner_id"] == b.zm_user["id"] and w["origin"] == "imported" and w["id"] != wid
    assert b.get(f"/api/worlds/{w['id']}").status_code == 200 and a.get(f"/api/worlds/{w['id']}").status_code == 404
    assert b.get("/api/users/me/stats").json()["worlds"]["imported"] == 1


def test_sse_generate_owned_by_creator(two_users):
    a, b = two_users
    ev = sse(a, "/api/worlds/generate", {"prompt": "仙侠门派"})
    wid = first(ev, "done")["world_id"]
    assert a.get(f"/api/worlds/{wid}").json()["owner_id"] == a.zm_user["id"]
    assert b.get(f"/api/worlds/{wid}").status_code == 404


def test_events_seen_cannot_touch_other_world(two_users):
    a, b = two_users
    wa = make_world(a)["id"]
    ev = a.post(f"/api/worlds/{wa}/god/inject", json={"content": "码头突发大火"}).json()
    wb = make_world(b)["id"]
    b.post(f"/api/worlds/{wb}/events/seen", json={"ids": [ev["id"]]})
    assert not next(e for e in a.get(f"/api/worlds/{wa}/events").json() if e["id"] == ev["id"])["seen"]


def test_mode0_anonymous_is_demo_and_hidden_from_users(core_env):
    with new_client() as anon:
        w = make_world(anon)
        assert w["owner_id"] == "u_demo"
        assert anon.get(f"/api/worlds/{w['id']}").status_code == 200
        with user_client() as u:
            assert u.get("/api/worlds").json() == [] and u.get(f"/api/worlds/{w['id']}").status_code == 404
        assert anon.get("/api/users/me/stats").json()["worlds"]["total"] == 1


def test_mode1_anonymous_rejected(core_env, monkeypatch):
    setenv(monkeypatch, ZM_AUTH_REQUIRED=1)
    with new_client() as anon:
        for method, path in [("get", "/api/worlds"), ("post", "/api/worlds"), ("post", "/api/worlds/generate"),
                             ("post", "/api/education/generate"), ("get", "/api/assets/x"),
                             ("get", "/api/users/me/stats"), ("get", "/api/users/me/learning"),
                             ("get", "/api/users/me/preferences"), ("post", "/api/reports")]:
            r = getattr(anon, method)(path, **({"json": {"prompt": "x"}} if method == "post" else {}))
            assert r.status_code == 401 and code(r) == "unauthorized", f"{method} {path}: {r.status_code}"
        me = anon.get("/api/auth/me")
        assert me.status_code == 401 and me.json()["auth_required"] is True and me.json()["acting_as"] is None
        for path in ("/api/health", "/api/safety/policy"):
            assert anon.get(path).status_code == 200
        assert anon.get("/api/health").json()["auth"]["required"] is True
        r, _ = register(anon)
        assert r.status_code == 201
        w = make_world(anon)
        assert anon.get(f"/api/worlds/{w['id']}").status_code == 200
        ev = sse(anon, f"/api/worlds/{w['id']}/turns", {"action": "四处看看"})  # SSE 靠 cookie 鉴权
        assert first(ev, "done")
        anon.cookies.clear()
        r = anon.post(f"/api/worlds/{w['id']}/turns", json={"action": "x"})
        assert r.status_code == 401 and "text/event-stream" not in r.headers.get("content-type", "")


def test_migration_old_db_to_demo(tmp_path, monkeypatch, caplog):
    data = tmp_path / "old"
    data.mkdir()
    con = sqlite3.connect(data / "zhimeng.db")
    con.execute("CREATE TABLE worlds (id VARCHAR PRIMARY KEY, title VARCHAR, genre VARCHAR, tone VARCHAR, mode VARCHAR,"
                " status VARCHAR, data JSON, created_at DATETIME, updated_at DATETIME)")
    con.execute("INSERT INTO worlds VALUES ('w_old1','旧世界','悬疑','','story','active',?,"
                "'2026-10-19 08:00:00','2026-10-19 08:00:00')", (json.dumps({"id": "w_old1", "title": "旧世界"}),))
    con.execute("CREATE TABLE reports (id VARCHAR PRIMARY KEY, world_id VARCHAR, turn_id VARCHAR, content VARCHAR,"
                " reason VARCHAR, status VARCHAR, created_at DATETIME)")
    con.commit()
    con.close()
    monkeypatch.setenv("ZM_FORCE_FALLBACK", "1")
    monkeypatch.setenv("ZM_DATA_DIR", str(data))
    monkeypatch.delenv("ZM_DEMO_PASSWORD", raising=False)
    from app import db
    from app.config import get_settings
    get_settings.cache_clear()
    db.reset_engine()
    caplog.set_level(logging.DEBUG)
    try:
        with new_client() as c:
            lst = c.get("/api/worlds").json()
            assert [w["id"] for w in lst] == ["w_old1"] and lst[0]["owner_id"] == "u_demo"
            pwf = data / "demo_password.txt"
            assert pwf.exists() and stat.S_IMODE(os.stat(pwf).st_mode) == 0o600
            pw = pwf.read_text().strip()
            assert len(pw) >= 16 and pw not in caplog.text
            r = c.post("/api/auth/login", json={"login": "demo", "password": pw})
            assert r.status_code == 200 and r.json()["user"]["id"] == "u_demo"
            assert stat.S_IMODE(os.stat(data / "jwt_secret").st_mode) == 0o600
            assert c.get("/api/worlds/w_old1").json()["origin"] == "generated"
        cols = {r[1] for r in sqlite3.connect(data / "zhimeng.db").execute("PRAGMA table_info(reports)")}
        assert "reporter_id" in cols
        db.reset_engine()  # 重启：幂等，密码文件不变
        with new_client() as c:
            assert c.post("/api/auth/login", json={"login": "demo", "password": pw}).status_code == 200
    finally:
        get_settings.cache_clear()
        db.reset_engine()


def test_jwt_secret_persisted_across_restart(core_env):
    from app import db
    with new_client() as c:
        register(c)
        acc = c.cookies.get("zm_access")
    db.reset_engine()
    from app.auth import security
    security._secret_cache.clear()
    with new_client() as c2:
        assert c2.get("/api/auth/me", headers={"Cookie": f"zm_access={acc}"}).status_code == 200


def test_preferences_put_patch_and_minor_floor(core_env):
    with user_client() as u:
        p = u.get("/api/users/me/preferences").json()["preferences"]
        assert p["minor_mode"] is False and p["education"]["auto_summary"] is True
        p = u.patch("/api/users/me/preferences", json={"tts_enabled": False, "education": {"grade": "初二"}}).json()
        assert p["preferences"]["tts_enabled"] is False and p["preferences"]["education"]["grade"] == "初二"
        p = u.put("/api/users/me/preferences", json={"autoplay_audio": True}).json()["preferences"]
        assert p["autoplay_audio"] is True and p["tts_enabled"] is True and p["education"]["grade"] is None  # PUT 回默认
        assert code(u.patch("/api/users/me/preferences", json={"nope": 1})) == "validation_error"
        assert code(u.patch("/api/users/me/preferences", json={"rating": "x"})) == "validation_error"
        assert u.patch("/api/users/me/preferences", json={"minor_mode": True}).json()["preferences"]["minor_mode"]
        w = make_world(u, minor_mode=False, rating="mature")
        assert w["minor_mode"] is True and w["rating"] in ("all", "teen")
        st = u.patch(f"/api/worlds/{w['id']}/settings", json={"minor_mode": False, "rating": "mature"})
        assert st.status_code == 200 and st.json()["minor_mode"] is True and st.json()["rating"] != "mature"
        assert set(st.headers["x-zm-clamped"].split(",")) == {"minor_mode", "rating"}
        ed = first(sse(u, "/api/education/generate", {"source_text": "赤壁之战发生在公元208年。", "minor_mode": False}), "world")
        assert ed["minor_mode"] is True
        assert code(u.patch("/api/users/me/preferences", json={"minor_mode": False})) == "wrong_password"
        assert code(u.put("/api/users/me/preferences", json={})) == "wrong_password"  # PUT 回默认 = 关闭，也要密码
        off = u.patch("/api/users/me/preferences", json={"minor_mode": False, "current_password": PW})
        assert off.status_code == 200 and off.json()["preferences"]["minor_mode"] is False


def test_prefs_minor_clamps_existing_world_on_read(core_env):
    with user_client() as u:
        w = make_world(u, minor_mode=False, rating="mature")
        assert w["minor_mode"] is False and w["rating"] == "mature"
        u.patch("/api/users/me/preferences", json={"minor_mode": True})
        got = u.get(f"/api/worlds/{w['id']}").json()
        assert got["minor_mode"] is True and got["rating"] == "teen"


def test_education_defaults_from_prefs(core_env):
    with user_client() as u:
        u.patch("/api/users/me/preferences", json={"education": {"grade": "初二", "subject": "历史"}})
        ev = sse(u, "/api/education/generate", {"source_text": "赤壁之战发生在公元208年。"})
        w = first(ev, "world")
        assert w["minor_mode"] is True  # 教育模式请求默认 minor_mode=true 不变
        rec = u.get("/api/users/me/learning").json()["items"][0]
        assert rec["grade"] == "初二" and rec["subject"] == "历史"


def test_stats_and_learning(two_users):
    a, b = two_users
    wid = make_world(a)["id"]
    a.post(f"/api/worlds/{wid}/confirm")
    sse(a, f"/api/worlds/{wid}/turns", {"action": "我去码头"})
    a.post(f"/api/worlds/{wid}/god/inject", json={"content": "码头突发大火"})
    a.post(f"/api/worlds/{wid}/assets/illustration", json={"prompt": "雨夜"})
    a.post("/api/reports", json={"world_id": wid, "content": "x", "reason": "其他"})
    ed = first(sse(a, "/api/education/generate", {"source_text": "赤壁之战发生在公元208年，孙刘联军大败曹操。",
                                                  "subject": "历史"}), "world")
    a.post(f"/api/worlds/{ed['id']}/confirm")
    sse(a, f"/api/worlds/{ed['id']}/turns", {"action": "我去江边"})
    s0 = a.get("/api/users/me/stats").json()
    assert s0["learning"]["summaries"] == 0 and s0["learning"]["latest"]["summary"] is None
    summ = a.get(f"/api/worlds/{ed['id']}/education/summary").json()
    assert summ["status"] == "complete"
    s = a.get("/api/users/me/stats").json()
    assert s["worlds"] == {"total": 2, "story": 1, "education": 1, "draft": 0, "active": 2, "ended": 0, "imported": 0}
    assert s["saves"]["slots"] == 2 and s["play"]["turns"] == 2 and s["play"]["injected_events"] == 1
    assert s["play"]["memories"] > 0 and s["play"]["first_played_at"] and s["assets"]["image"] >= 1
    assert s["reports_submitted"] == 1
    assert s["learning"]["worlds"] == 1 and s["learning"]["turns"] == 1 and s["learning"]["summaries"] == 1
    latest = s["learning"]["latest"]
    assert latest["world_id"] == ed["id"] and latest["subject"] == "历史"
    assert latest["summary"]["key_points"] == summ["key_points"] and latest["summary"]["turn_count"] == 1
    assert {w["id"] for w in s["recent_worlds"]} == {wid, ed["id"]}
    lr = a.get("/api/users/me/learning?limit=1&offset=0").json()
    assert lr["total"] == 1 and lr["limit"] == 1 and lr["items"][0]["world_id"] == ed["id"]
    assert a.get("/api/users/me/learning?limit=0").status_code == 422
    sb = b.get("/api/users/me/stats").json()
    assert sb["worlds"]["total"] == 0 and sb["learning"]["latest"] is None and sb["play"]["turns"] == 0
    assert b.get("/api/users/me/learning").json() == {"items": [], "total": 0, "limit": 20, "offset": 0}
