"""前端第 3 轮诉求（FRONTEND_REQUESTS.md §3）的后端契约测试：开局音画、regenerate refine、举报隔离、细粒度 token。"""
from __future__ import annotations

import time

from test_core import PROMPT, first, make_world, sse


def test_chunk_filter_emits_fine_deltas(core_env, monkeypatch):
    from app.services import guard
    monkeypatch.setattr(guard, "filter_chunk", lambda t, minor_mode=False: t)
    f = guard.ChunkFilter(hold=8)
    outs = [f.feed(ch) for ch in "一二三四五六七八九十甲乙丙丁戊己庚辛"]  # 每次 1 字
    # 前 hold 个字被延迟；之后每喂 1 字就吐 1 字（不会攒成大块）
    assert outs[:8] == [""] * 8 and all(len(o) == 1 for o in outs[8:])
    assert "".join(outs) + f.flush() == "一二三四五六七八九十甲乙丙丁戊己庚辛"


def test_fallback_tokens_are_fine_grained(client):
    wid = make_world(client)
    evs = sse(client, f"/api/worlds/{wid}/turns", {"action": "四处看看"})
    toks = [d["text"] for e, d in evs if e == "token"]
    assert len(toks) > 10 and max(len(t) for t in toks[:-1]) <= 4


def test_opening_media_image_and_audio(client):
    wid = make_world(client)
    for _ in range(50):
        rows = client.get(f"/api/worlds/{wid}/assets").json()
        kinds = {a["type"] for a in rows if a.get("turn_id") is None}
        if {"image", "audio"} <= kinds:
            break
        time.sleep(0.1)
    assert {"image", "audio"} <= kinds


def test_regenerate_refine_and_gen_request(client):
    w = first(sse(client, "/api/worlds/generate", {"prompt": PROMPT}), "world")
    assert w["gen_request"]["prompt"] == PROMPT and w["state"]["flags"]["gen_request"]["prompt"] == PROMPT
    w2 = first(sse(client, f"/api/worlds/{w['id']}/regenerate", {"refine": "多一点悬疑"}), "world")
    assert w2["id"] == w["id"]
    assert w2["gen_request"]["prompt"] == PROMPT and w2["gen_request"]["refine"] == "多一点悬疑"
    w3 = first(sse(client, f"/api/worlds/{w['id']}/regenerate", {"refine": ""}), "world")
    assert w3["gen_request"]["refine"] is None


def test_reports_scoped_by_world(client, monkeypatch):
    a, b = make_world(client), make_world(client)
    client.post("/api/reports", json={"world_id": a, "content": "x", "reason": "r"})
    client.post("/api/reports", json={"world_id": b, "content": "y", "reason": "r"})
    ra = client.get(f"/api/reports?world_id={a}").json()
    assert ra and all(r["world_id"] == a for r in ra)
    r = client.get("/api/reports")
    assert r.status_code == 403 and r.json()["code"] == "forbidden"  # 未配置 ZM_ADMIN_TOKEN → 全量禁用
    from app.config import get_settings
    monkeypatch.setenv("ZM_ADMIN_TOKEN", "t0ken")
    get_settings.cache_clear()
    assert client.get("/api/reports", headers={"X-Admin-Token": "bad"}).status_code == 403
    full = client.get("/api/reports", headers={"X-Admin-Token": "t0ken"}).json()
    assert {r["world_id"] for r in full} >= {a, b}


def test_director_stream_resumes_after_disconnect(core_env, monkeypatch):
    """真实模式下旁白流首字后断开 → 带已写部分续写，不丢回合。"""
    import asyncio
    import types

    from app.agents import director
    from app.llm.client import LLMUnavailable
    calls = []

    async def fake_stream(msgs, **kw):
        calls.append(msgs)
        if len(calls) == 1:
            yield "前半段"
            raise LLMUnavailable("peer closed")
        assert msgs[-2] == {"role": "assistant", "content": "前半段"}
        yield "后半段"
    monkeypatch.setattr(director, "llm_enabled", lambda: True)
    from app.llm import client as llmc
    monkeypatch.setattr(llmc, "chat_stream", fake_stream)
    monkeypatch.setattr(director.prompts, "director_messages", lambda *a, **k: [{"role": "user", "content": "x"}])

    async def run():
        return [c async for _, c in director.narrate_stream(
            types.SimpleNamespace(minor_mode=False), "看看", memory_ctx="", recent="", npc_ctx="", events_ctx="", inject_ctx="", focus=None,
            event_lines=[], injects=[], turn=1)]
    assert "".join(asyncio.run(run())) == "前半段后半段" and len(calls) == 2


def test_stale_enriching_world_is_recovered_on_startup(client):
    """进程在补全中途被重启：启动时不再永远停在 enriching（兜底模式直接标记 local）。"""
    from app.agents.world_builder import resume_stale_enrichment
    from app.services import repo
    wid = make_world(client)
    w = repo.load_world(wid)
    w.detail_status = "enriching"
    repo.save_world(w)
    assert resume_stale_enrichment() == 1
    assert client.get(f"/api/worlds/{wid}").json()["detail_status"] == "local"
