"""v1.5 角色分支选择：选项生成（含后果提示、兜底可复现）、剧情树、回到分支点另选、记忆/状态回溯、隔离、旧数据迁移。"""
from __future__ import annotations

import json
import sqlite3

import pytest

from auth_helpers import new_client, user_client
from test_core import first, sse

DEMO_PROMPT = "织梦演示：迷雾小镇的古钟"
TECH_WORDS = ("AI", "ai", "模型", "系统", "API", "fallback", "branch", "节点", "接口", "LLM", "token")


def new_world(c, prompt: str = DEMO_PROMPT) -> dict:
    r = c.post("/api/worlds", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    w = r.json()
    c.post(f"/api/worlds/{w['id']}/confirm")
    return w


def play(c, wid: str, **body) -> dict:
    ev = sse(c, f"/api/worlds/{wid}/turns", body)
    d = first(ev, "done")
    assert d and "turn" in d, ev[-3:]
    return d


def assert_choices(opts: list[dict]) -> None:
    assert 2 <= len(opts) <= 4
    for o in opts:
        assert o["id"] and o["text"].strip()
        assert o.get("hint") and len(o["hint"]) <= 20, o
        assert not any(w in o["text"] + o["hint"] for w in TECH_WORDS), o


# ---------------------------------------------------------------- 选项
def test_options_have_hints_and_are_reproducible(client):
    a, b = new_world(client), new_world(client)
    assert a["id"] != b["id"]
    assert_choices(a["opening_options"])
    assert a["opening_options"] == b["opening_options"]
    seq = ["opt_1", "opt_2", "opt_3"]
    runs = []
    for w in (a, b):
        out = []
        for oid in seq:
            d = play(client, w["id"], option_id=oid)
            assert_choices(d["turn"]["options"])
            assert d["turn"]["option_id"] == oid
            out.append((d["turn"]["action"], d["turn"]["narration"], d["turn"]["options"], d["state"]["stats"]))
        runs.append(out)
    assert runs[0] == runs[1]  # 同样的设定 + 同样的点选顺序 → 每次完全相同（录屏可复现）
    opts = client.get(f"/api/worlds/{a['id']}/options").json()
    assert opts["options"] == runs[0][-1][2] and opts["taken"] == {}


def test_option_choices_diverge_story(client):
    w = new_world(client)
    wid = w["id"]
    t1 = play(client, wid, option_id="opt_1")["turn"]  # 走进酒馆和老乔聊聊
    texts = {o["id"]: o["text"] for o in t1["options"]}
    trust = next(k for k, v in texts.items() if v.startswith("相信"))
    doubt = next(k for k, v in texts.items() if v.startswith("当面质疑"))
    char = next(o["character_id"] for o in t1["options"] if o["id"] == trust)
    assert char
    d_doubt = play(client, wid, option_id=doubt)
    client.post(f"/api/worlds/{wid}/branches/checkout", json={"turn_id": t1["id"]})
    d_trust = play(client, wid, option_id=trust)
    assert d_trust["branch"]["forked"] is True and d_trust["branch"]["label"] == "支线1"
    assert "说漏了一句" in d_doubt["turn"]["narration"] and "松了口气" in d_trust["turn"]["narration"]
    assert d_doubt["turn"]["facts"] != d_trust["turn"]["facts"]

    def aff(world):
        c = next(x for x in world["characters"] if x["id"] == char)
        return next(r["affinity"] for r in c["relations"] if r["target_id"] == "player")
    trust_aff = aff(client.get(f"/api/worlds/{wid}").json())
    client.post(f"/api/worlds/{wid}/branches/checkout", json={"turn_id": d_doubt["turn"]["id"]})
    doubt_aff = aff(client.get(f"/api/worlds/{wid}").json())
    assert trust_aff - doubt_aff >= 10  # 相信 +8 / 质疑 -8（再叠加角色自身反应）


def test_free_input_and_option_only_validation(client):
    wid = new_world(client)["id"]
    d = play(client, wid, action="我在广场上四处看看")
    assert d["turn"]["option_id"] is None and d["turn"]["action"] == "我在广场上四处看看"
    r = client.post(f"/api/worlds/{wid}/turns", json={"action": "", "option_id": None})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    ev = sse(client, f"/api/worlds/{wid}/turns", {"option_id": "opt_99"})
    assert first(ev, "error")["retryable"] is False


# ---------------------------------------------------------------- 剧情树 / 回溯另选
def test_branch_tree_checkout_and_state_restore(client):
    wid = new_world(client)["id"]
    d1 = play(client, wid, option_id="opt_1")
    d2 = play(client, wid, option_id="opt_2")
    d2b = play(client, wid, option_id="opt_1")
    t1, t2, t3 = d1["turn"], d2["turn"], d2b["turn"]
    assert (t2["parent_turn_id"], t3["parent_turn_id"]) == (t1["id"], t2["id"]) and t1["parent_turn_id"] is None
    assert {t["branch_id"] for t in (t1, t2, t3)} == {"main"}

    r = client.post(f"/api/worlds/{wid}/branches/checkout", json={"turn_id": t1["id"]})
    assert r.status_code == 200
    body = r.json()
    assert [t["id"] for t in body["turns"]] == [t1["id"]]
    assert body["head_turn_id"] == t1["id"] and body["world"]["head_turn_id"] == t1["id"]
    assert body["world"]["state"] == d1["state"]  # 世界状态回到第 1 回合刚结束时
    assert body["options"] == t1["options"] and body["taken"] == {"opt_2": t2["id"]}
    assert [t["id"] for t in client.get(f"/api/worlds/{wid}/turns").json()] == [t1["id"]]
    assert client.get(f"/api/worlds/{wid}/options").json()["taken"] == {"opt_2": t2["id"]}

    d4 = play(client, wid, option_id="opt_3")
    t4 = d4["turn"]
    assert d4["branch"]["forked"] and t4["parent_turn_id"] == t1["id"] and t4["branch_id"] != "main"
    assert t4["index"] == 2
    d5 = play(client, wid, option_id="opt_1")  # 在新支线的线尾继续 → 不再分叉
    assert d5["branch"]["forked"] is False and d5["turn"]["branch_id"] == t4["branch_id"]

    tree = client.get(f"/api/worlds/{wid}/branches").json()
    assert tree["head_turn_id"] == d5["turn"]["id"] and tree["branch_id"] == t4["branch_id"]
    assert [b["label"] for b in tree["branches"]] == ["主线", "支线1"]
    sub = tree["branches"][1]
    assert sub["fork_turn_id"] == t1["id"] and sub["fork_index"] == 1 and sub["turn_count"] == 2
    assert sub["title"] == t4["action"] and sub["is_current"] and not tree["branches"][0]["is_current"]
    nodes = {n["id"]: n for n in tree["nodes"]}
    assert tree["nodes"][0]["id"] == "opening" and nodes["opening"]["children"] == [t1["id"]]
    assert set(nodes[t1["id"]]["children"]) == {t2["id"], t4["id"]}
    assert {n for n, v in nodes.items() if v["on_path"]} == {"opening", t1["id"], t4["id"], d5["turn"]["id"]}
    taken = {c["id"]: c["taken_turn_id"] for c in nodes[t1["id"]]["choices"]}
    assert taken["opt_2"] == t2["id"] and taken["opt_3"] == t4["id"]
    assert nodes[t4["id"]]["hint"] and nodes[t4["id"]]["preview"]
    for b in tree["branches"]:
        assert not any(w in b["label"] + b["title"] for w in TECH_WORDS)
    # 只预览不切换
    p = client.get(f"/api/worlds/{wid}/branches/path", params={"turn_id": t3["id"]}).json()
    assert [t["id"] for t in p["turns"]] == [t1["id"], t2["id"], t3["id"]] and p["head_turn_id"] == d5["turn"]["id"]
    assert client.get(f"/api/worlds/{wid}/branches/path", params={"turn_id": "opening"}).json()["turns"] == []
    # 切回主线线尾：状态与当时完全一致
    back = client.post(f"/api/worlds/{wid}/branches/checkout", json={"turn_id": t3["id"]}).json()
    assert back["world"]["state"] == d2b["state"] and back["branch_id"] == "main"
    assert [t["id"] for t in back["turns"]] == [t1["id"], t2["id"], t3["id"]]


def test_memory_and_events_follow_current_path(client):
    wid = new_world(client)["id"]
    t1 = play(client, wid, option_id="opt_1")["turn"]
    doubt = next(o["id"] for o in t1["options"] if o["text"].startswith("当面质疑"))
    trust = next(o["id"] for o in t1["options"] if o["text"].startswith("相信"))
    d_doubt = play(client, wid, option_id=doubt)
    mem = [m["content"] for m in client.get(f"/api/worlds/{wid}/memory?limit=500").json()]
    assert any("质疑" in m for m in mem)
    doubt_events = {e["id"] for e in d_doubt["turn"]["events"]}

    d_trust = play(client, wid, option_id=trust, from_turn_id=t1["id"])  # 一步完成「回到分支点另选」
    assert d_trust["branch"]["forked"] and d_trust["turn"]["parent_turn_id"] == t1["id"]
    mem = [m["content"] for m in client.get(f"/api/worlds/{wid}/memory?limit=500").json()]
    assert any("相信" in m for m in mem) and not any("质疑" in m for m in mem)
    ans = client.post(f"/api/worlds/{wid}/memory/query", json={"question": "我当面质疑了谁"}).json()
    assert not any("质疑" in c["content"] for c in ans["citations"])
    ev_ids = {e["id"] for e in client.get(f"/api/worlds/{wid}/events?type=&limit=500").json()}
    assert ev_ids and not (ev_ids & doubt_events)
    god = client.get(f"/api/worlds/{wid}/god/npcs").json()
    assert all(t["turn"] <= 2 for g in god for t in g["trajectory"])
    exp = client.get(f"/api/worlds/{wid}/export").json()
    assert [t["id"] for t in exp["turns"]] == [t1["id"], d_trust["turn"]["id"]]
    assert set(exp["turn_snapshots"]) == {t1["id"], d_trust["turn"]["id"]}

    # 下一回合检索到的记忆也只来自当前路径
    d3 = play(client, wid, action="回想老乔说过的话")
    from app.memory import store
    rows = store.list_memories(wid, limit=1000)
    assert not any("质疑" in r.content for r in rows)
    assert d3["turn"]["parent_turn_id"] == d_trust["turn"]["id"]


def test_checkout_opening_and_from_opening(client):
    w = new_world(client)
    wid = w["id"]
    t1 = play(client, wid, option_id="opt_1")["turn"]
    r = client.post(f"/api/worlds/{wid}/branches/checkout", json={"turn_id": None}).json()
    assert r["head_turn_id"] is None and r["turns"] == [] and r["world"]["state"]["turn"] == 0
    assert r["options"] == w["opening_options"] and r["taken"] == {"opt_1": t1["id"]}
    d = play(client, wid, option_id="opt_2")
    assert d["branch"]["forked"] and d["turn"]["index"] == 1 and d["turn"]["parent_turn_id"] is None
    d3 = play(client, wid, option_id="opt_3", from_turn_id="opening")
    assert d3["branch"]["label"] == "支线2"
    tree = client.get(f"/api/worlds/{wid}/branches").json()
    assert len(tree["opening"]["children"]) == 3 and len(tree["branches"]) == 3
    assert tree["current_node_id"] == d3["turn"]["id"]  # 前端草案兼容字段
    rw = client.post(f"/api/worlds/{wid}/branches/rewind", json={"to_node_id": t1["id"]}).json()
    assert rw["current_node_id"] == t1["id"] and rw["branch_id"] == "main"


def test_retry_rules_with_branches(client):
    wid = new_world(client)["id"]
    t1 = play(client, wid, option_id="opt_1")["turn"]
    t2 = play(client, wid, option_id="opt_2")["turn"]
    client.post(f"/api/worlds/{wid}/branches/checkout", json={"turn_id": t1["id"]})
    err = first(sse(client, f"/api/worlds/{wid}/turns/retry"), "error")
    assert err and err["retryable"] is False and "另选" in err["message"]
    assert [t["id"] for t in client.get(f"/api/worlds/{wid}/branches/path", params={"turn_id": t2["id"]}).json()["turns"]] \
        == [t1["id"], t2["id"]]  # 什么都没被覆盖
    d = play(client, wid, option_id="opt_3")  # 新支线
    again = first(sse(client, f"/api/worlds/{wid}/turns/retry"), "done")  # 线尾可以重写，仍在同一条支线
    assert again["turn"]["branch_id"] == d["turn"]["branch_id"] and again["turn"]["parent_turn_id"] == t1["id"]
    assert again["turn"]["action"] == d["turn"]["action"] and again["turn"]["id"] != d["turn"]["id"]
    tree = client.get(f"/api/worlds/{wid}/branches").json()
    assert len(tree["nodes"]) == 4 and len(tree["branches"]) == 2


def test_injection_pending_again_on_other_branch(client):
    wid = new_world(client)["id"]
    t1 = play(client, wid, option_id="opt_1")["turn"]
    ev = client.post(f"/api/worlds/{wid}/god/inject", json={"content": "钟楼突然响起了钟声", "impact": "low"}).json()
    d2 = play(client, wid, option_id="opt_3")
    assert ev["id"] in {e["id"] for e in d2["turn"]["events"]}
    d3 = play(client, wid, option_id="opt_4", from_turn_id=t1["id"])  # 另一条线同样会经历这件事
    assert ev["id"] in {e["id"] for e in d3["turn"]["events"]}


# ---------------------------------------------------------------- 隔离
def test_branch_endpoints_isolated(core_env):
    a, b = user_client(), user_client()
    with a, b:
        wa, wb = new_world(a)["id"], new_world(b)["id"]
        ta = play(a, wa, option_id="opt_1")["turn"]
        tb = play(b, wb, option_id="opt_1")["turn"]
        for method, path, body in [("get", f"/api/worlds/{wa}/branches", None),
                                   ("get", f"/api/worlds/{wa}/branches/path?turn_id={ta['id']}", None),
                                   ("post", f"/api/worlds/{wa}/branches/checkout", {"turn_id": ta["id"]}),
                                   ("post", f"/api/worlds/{wa}/branches/rewind", {"to_node_id": ta["id"]})]:
            r = getattr(b, method)(path, **({"json": body} if body is not None else {}))
            assert r.status_code == 404 and r.json()["code"] == "not_found", (path, r.text)
        # 自己的世界 + 别人的回合 id → 404（不暴露存在性）
        r = b.post(f"/api/worlds/{wb}/branches/checkout", json={"turn_id": ta["id"]})
        assert r.status_code == 404 and r.json() == {"detail": "没有找到这段剧情", "code": "not_found"}
        assert b.get(f"/api/worlds/{wb}/branches/path", params={"turn_id": ta["id"]}).status_code == 404
        ev = sse(b, f"/api/worlds/{wb}/turns", {"option_id": "opt_1", "from_turn_id": ta["id"]})
        assert first(ev, "error")["message"] == "没有找到这段剧情"
        assert [t["id"] for t in b.get(f"/api/worlds/{wb}/turns").json()] == [tb["id"]]
        r = b.post(f"/api/worlds/{wa}/turns", json={"option_id": "opt_1", "from_turn_id": ta["id"]})
        assert r.status_code == 404


# ---------------------------------------------------------------- 旧数据迁移
def test_legacy_turns_migrate_to_main_line(tmp_path, monkeypatch):
    from app import db
    from app.config import get_settings
    from app.memory import store
    data = tmp_path / "legacy"
    monkeypatch.setenv("ZM_FORCE_FALLBACK", "1")
    monkeypatch.setenv("ZM_DATA_DIR", str(data))
    monkeypatch.setenv("STREAM_DELAY", "0")

    def restart():
        get_settings.cache_clear()
        db.reset_engine()
        store.reset_chroma()
    restart()
    try:
        with new_client() as c:
            wid = new_world(c)["id"]
            ids = [play(c, wid, option_id="opt_1")["turn"]["id"] for _ in range(3)]
        # 退回 v1.4 的表结构：去掉 v1.5 列、世界 JSON 里没有 head_turn_id / branch_id
        con = sqlite3.connect(data / "zhimeng.db")
        con.execute("DROP INDEX IF EXISTS ix_turns_parent_turn_id")
        for col in ("parent_turn_id", "branch_id", "option_id", "active", "state_after"):
            con.execute(f"ALTER TABLE turns DROP COLUMN {col}")
        for t in ("events", "memories", "summaries", "trajectories"):
            con.execute(f"ALTER TABLE {t} DROP COLUMN branch_id")
            con.execute(f"ALTER TABLE {t} DROP COLUMN active")
        con.execute("DROP TABLE branches")
        raw = json.loads(con.execute("SELECT data FROM worlds WHERE id = ?", (wid,)).fetchone()[0])
        raw.pop("head_turn_id", None)
        raw.pop("branch_id", None)
        con.execute("UPDATE worlds SET data = ? WHERE id = ?", (json.dumps(raw, ensure_ascii=False), wid))
        con.commit()
        con.close()
        restart()
        with new_client() as c:
            assert [t["id"] for t in c.get(f"/api/worlds/{wid}/turns").json()] == ids
            tree = c.get(f"/api/worlds/{wid}/branches").json()
            assert [b["label"] for b in tree["branches"]] == ["主线"] and tree["head_turn_id"] == ids[-1]
            nodes = {n["id"]: n for n in tree["nodes"]}
            assert [nodes[i]["parent_turn_id"] for i in ids] == [None, ids[0], ids[1]]
            assert all(nodes[i]["on_path"] and nodes[i]["branch_id"] == "main" for i in ids)
            assert c.get(f"/api/worlds/{wid}/memory?limit=500").json()  # 旧记忆都在当前路径上
            d = play(c, wid, option_id="opt_1")  # 线尾继续 → 仍是主线
            assert d["branch"] == {"branch_id": "main", "label": "主线", "forked": False, "head_turn_id": d["turn"]["id"]}
            assert d["turn"]["parent_turn_id"] == ids[-1]
            r = c.post(f"/api/worlds/{wid}/branches/checkout", json={"turn_id": ids[0]}).json()  # 旧回合也能回溯
            assert [t["id"] for t in r["turns"]] == [ids[0]] and r["world"]["state"]["turn"] == 1
            assert play(c, wid, option_id="opt_2")["branch"]["forked"] is True
        restart()  # 再启动一次：迁移幂等
        with new_client() as c:
            assert len(c.get(f"/api/worlds/{wid}/branches").json()["branches"]) == 2
    finally:
        restart()


def test_agent_options_sanitized(client, monkeypatch):
    """导演 Agent 给的选项：补齐缺失的后果提示、按文本点名纠正角色 id、超过 4 个截断、少于 2 个用规则补。"""
    from app.agents import director
    real = director.extract
    payload = {"options": [{"text": "当面质疑老乔", "character_id": "c_2"}, {"text": "调查壁炉", "hint": "也许有暗格"},
                           {"text": "前往钟楼"}, {"text": "去找阿梨"}, {"text": "多余的第五个"}]}

    async def fake(world, action, narration, focus):
        base = await real(world, action, narration, focus)
        base.update(payload)
        return base
    monkeypatch.setattr(director, "extract", fake)
    wid = new_world(client)["id"]
    opts = play(client, wid, option_id="opt_1")["turn"]["options"]
    assert_choices(opts)
    assert len(opts) == 4 and opts[0]["character_id"] == "c_1" and opts[1]["hint"] == "也许有暗格"
    payload["options"] = [{"text": "只有一个"}]
    opts = play(client, wid, option_id="opt_1")["turn"]["options"]
    assert_choices(opts)
    assert "只有一个" not in [o["text"] for o in opts]
