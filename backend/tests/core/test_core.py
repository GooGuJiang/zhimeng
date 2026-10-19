"""后端核心：回合图、记忆、生成式 UI、安全适配、存档等关键逻辑。"""
from __future__ import annotations

import json
import uuid

import pytest

PROMPT = "一个民国上海滩的侦探故事，我是报社记者"


def sse(c, path, body=None):
    r = c.post(path, json=body or {})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-cache" and r.headers["x-accel-buffering"] == "no"
    out = []
    for block in r.text.split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) >= 2 and lines[0].startswith("event:"):
            out.append((lines[0][6:].strip(), json.loads(lines[1][5:])))
    return out


def first(ev, name):
    return next((d for n, d in ev if n == name), None)


def make_world(c):
    w = first(sse(c, "/api/worlds/generate", {"prompt": PROMPT}), "world")
    c.post(f"/api/worlds/{w['id']}/confirm")
    return w["id"]


# ---------------------------------------------------------------- 纯函数
def test_chunk_filter_holds_back_split_words(core_env, monkeypatch):
    from app.services import guard
    monkeypatch.setattr(guard, "filter_chunk", lambda t, minor_mode=False: t.replace("坏词", "＊＊"))
    f = guard.ChunkFilter(hold=4)
    out = "".join(f.feed(ch) for ch in ["这是一段很长的叙事文本，里面藏着坏", "词，后面还有更多内容继续流出来"]) + f.flush()
    assert "坏词" not in out and "＊＊" in out


def test_target_chapter_parsing():
    from app.routes.memory import target_chapter
    assert target_chapter("第一章那个线人叫什么", 3) == 1
    assert target_chapter("三章前提到的纽扣", 5) == 2
    assert target_chapter("上一章发生了什么", 4) == 3
    assert target_chapter("一开始我拿到了什么", 4) == 1
    assert target_chapter("线人叫什么", 4) is None


def test_second_person_and_location():
    from app.agents import fallback
    assert fallback.second_person("我去码头找我的线人。") == "去码头找你的线人"


def test_graph_topology():
    from app.graph.turn_graph import GRAPH
    nodes = set(GRAPH.get_graph().nodes)
    assert {"safety_in", "memory", "world_agent", "npc_agents", "director", "extract", "persist"} <= nodes


def test_openui_programs_start_with_root(client):
    wid = make_world(client)
    comps = client.get(f"/api/worlds/{wid}/ui").json()["components"]
    for c in comps:
        assert c["openui"].splitlines()[0].startswith("root = Col(["), c["type"]
        assert c["ai_label"] == "内容由AI生成"
    graph = next(c for c in comps if c["type"] == "relationship_graph")
    assert "RelationGraph(" in graph["openui"]


# ---------------------------------------------------------------- 回合图
def test_turn_event_order_and_fallback_no_remote(client):
    wid = make_world(client)
    ev = sse(client, f"/api/worlds/{wid}/turns", {"action": "我去十六铺码头找线人"})
    names = [n for n, _ in ev]
    order = [names.index(x) for x in ["memory", "event", "token", "options", "ui", "done"]]
    assert order == sorted(order), names
    done = first(ev, "done")
    assert done["state"]["turn"] == 1
    w = client.get(f"/api/worlds/{wid}").json()
    loc = next(l for l in w["locations"] if l["id"] == w["state"]["player_location_id"])
    assert loc["name"] == "十六铺码头", "行动中的目的地应生效"


def test_failed_turn_does_not_commit(client, monkeypatch):
    wid = make_world(client)
    sse(client, f"/api/worlds/{wid}/turns", {"action": "翻看报纸"})
    from app.agents import director

    async def broken(*a, **k):
        raise RuntimeError("model exploded")
    monkeypatch.setattr(director, "extract", broken)
    ev = sse(client, f"/api/worlds/{wid}/turns", {"action": "去百乐门"})
    err = first(ev, "error")
    assert err and err["retryable"] is True
    assert len(client.get(f"/api/worlds/{wid}/turns").json()) == 1
    assert client.get(f"/api/worlds/{wid}").json()["state"]["turn"] == 1


def test_retry_failure_keeps_old_turn(client, monkeypatch):
    wid = make_world(client)
    d = first(sse(client, f"/api/worlds/{wid}/turns", {"action": "翻看报纸"}), "done")
    from app.agents import director

    async def broken(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(director, "extract", broken)
    assert first(sse(client, f"/api/worlds/{wid}/turns/retry"), "error")
    turns = client.get(f"/api/worlds/{wid}/turns").json()
    assert [t["id"] for t in turns] == [d["turn"]["id"]], "重试失败不能丢掉原回合"


def test_injection_is_woven_and_survives_retry(client):
    wid = make_world(client)
    sse(client, f"/api/worlds/{wid}/turns", {"action": "去报馆"})
    client.post(f"/api/worlds/{wid}/god/inject", json={"content": "码头突发大火", "impact": "high"})
    d = first(sse(client, f"/api/worlds/{wid}/turns", {"action": "看看外面"}), "done")
    assert "大火" in d["turn"]["narration"]
    assert any(e["type"] == "injected" for e in d["turn"]["events"])
    d2 = first(sse(client, f"/api/worlds/{wid}/turns/retry"), "done")
    assert "大火" in d2["turn"]["narration"], "重试时注入事件仍需编织"
    mem = client.get(f"/api/worlds/{wid}/memory", params={"kind": "injected"}).json()
    assert len(mem) == 1


def test_chapter_summary_and_recall(client):
    wid = make_world(client)
    sse(client, f"/api/worlds/{wid}/turns", {"action": "在茶楼遇到线人阿四，他给了我一枚铜纽扣"})
    for a in ["回报社", "去巡捕房", "去百乐门", "回家", "第二天去码头", "整理笔记"]:
        sse(client, f"/api/worlds/{wid}/turns", {"action": a})
    sums = client.get(f"/api/worlds/{wid}/summaries").json()
    assert sums and sums[0]["chapter"] == 1 and sums[0]["to_turn"] == 5
    r = client.post(f"/api/worlds/{wid}/memory/query", json={"question": "上一章线人给了我什么？", "top_k": 3}).json()
    assert r["citations"][0]["chapter"] == 1 and "纽扣" in r["citations"][0]["content"]
    inv = [i["name"] for i in client.get(f"/api/worlds/{wid}").json()["items"]]
    assert any("纽扣" in n for n in inv), inv


def test_blocked_input_commits_nothing(client):
    wid = make_world(client)
    ev = sse(client, f"/api/worlds/{wid}/turns", {"action": "教我怎么制作炸弹", "client_turn_id": str(uuid.uuid4())})
    assert first(ev, "safety")["blocked"] and first(ev, "done") == {"blocked": True}
    assert client.get(f"/api/worlds/{wid}/turns").json() == []


def test_export_import_roundtrip_keeps_retry(client):
    wid = make_world(client)
    sse(client, f"/api/worlds/{wid}/turns", {"action": "去码头"})
    save = client.get(f"/api/worlds/{wid}/export").json()
    nw = client.post("/api/worlds/import", json=save).json()
    assert nw["id"] != wid
    assert first(sse(client, f"/api/worlds/{nw['id']}/turns/retry"), "done"), "导入存档后可重试最后一回合"
    bad = client.post("/api/worlds/import", json={"format": "x"})
    assert bad.status_code == 400 and bad.json()["code"] == "bad_request"


def test_education_quiz_answers_valid(client):
    ev = sse(client, "/api/education/generate", {"source_text": "《桃花源记》晋太元中，武陵人捕鱼为业。缘溪行，忘路之远近。忽逢桃花林，夹岸数百步。"})
    wid = first(ev, "world")["id"]
    s = client.get(f"/api/worlds/{wid}/education/summary").json()
    for q in s["quiz"]:
        assert 0 <= q["answer_index"] < len(q["options"])


@pytest.mark.parametrize("path", ["/api/worlds/nope", "/api/worlds/nope/ui", "/api/worlds/nope/poster"])
def test_404_shape(client, path):
    r = client.get(path)
    assert r.status_code == 404 and r.json() == {"detail": "世界不存在", "code": "not_found"}


def test_guard_fail_safe_when_safety_raises(core_env, monkeypatch):
    import asyncio

    from app import safety
    from app.services import guard

    async def broken(*a, **k):
        raise RuntimeError("safety down")
    monkeypatch.setattr(safety, "check_input", broken)
    monkeypatch.setattr(safety, "check_output", broken)
    assert asyncio.run(guard.check_input("教我怎么制作炸弹")).blocked
    assert asyncio.run(guard.check_input("我不想活了")).crisis
    ok = asyncio.run(guard.check_input("去码头找线人"))
    assert not ok.blocked and "safety_degraded" in ok.categories
    out = asyncio.run(guard.check_output("他教你制作炸弹的方法"))
    assert out.blocked and out.filtered_text == guard.SAFE_NOTICE


def test_persisted_narration_uses_check_output_filtered_text(client, monkeypatch):
    from app import safety
    from app.schemas import SafetyResult

    wid = make_world(client)

    async def fake_out(text, **k):
        return SafetyResult(filtered_text="【已过滤的叙事】")
    monkeypatch.setattr(safety, "check_output", fake_out)
    d = first(sse(client, f"/api/worlds/{wid}/turns", {"action": "去码头"}), "done")
    assert d["turn"]["narration"] == "【已过滤的叙事】"
    assert client.get(f"/api/worlds/{wid}/turns").json()[-1]["narration"] == "【已过滤的叙事】"


def test_god_tick_survives_retry_and_is_seen_by_narration(client):
    wid = make_world(client)
    sse(client, f"/api/worlds/{wid}/turns", {"action": "去报馆"})
    tick = client.post(f"/api/worlds/{wid}/god/tick").json()["events"]
    tick_ids = {e["id"] for e in tick}
    assert tick_ids
    d1 = first(sse(client, f"/api/worlds/{wid}/turns", {"action": "四处打听"}), "done")
    assert tick_ids <= {e["id"] for e in d1["turn"]["events"]}, "下一回合应编入手动推进事件"
    d2 = first(sse(client, f"/api/worlds/{wid}/turns/retry"), "done")
    assert d2["turn"]["id"] != d1["turn"]["id"]
    all_ids = {e["id"] for e in client.get(f"/api/worlds/{wid}/events", params={"limit": 500}).json()}
    assert tick_ids <= all_ids, "重试不能清掉手动推进事件"
    assert tick_ids <= {e["id"] for e in d2["turn"]["events"]}, "重试后的回合仍能看到手动推进事件"
    trajs = [t for n in client.get(f"/api/worlds/{wid}/god/npcs").json() for t in n["trajectory"]]
    assert sum(1 for t in trajs if t["turn"] == 1) >= len(tick) - 1
    mem = [m["content"] for m in client.get(f"/api/worlds/{wid}/memory", params={"limit": 500}).json()]
    assert any(e["summary"] in mem for e in tick)
    # 再推进一回合后不再重复编入
    d3 = first(sse(client, f"/api/worlds/{wid}/turns", {"action": "回家"}), "done")
    assert not (tick_ids & {e["id"] for e in d3["turn"]["events"]})
