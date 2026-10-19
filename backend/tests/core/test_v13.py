"""v1.3：资产 status/version/updated_at + 原地升级刷新信号、并行输入复核、提交后输出复核。"""
from __future__ import annotations

import asyncio

from test_core import first, make_world, sse


def _asset(client, wid):
    return client.post(f"/api/worlds/{wid}/assets/illustration", json={"prompt": "雨夜码头"}).json()


def test_asset_version_url_and_status(client, monkeypatch):
    from app import multimodal
    from app.multimodal import assets as mm
    wid = make_world(client)
    a = _asset(client, wid)
    assert a["status"] == "ready" and a["version"] == 1 and a["updated_at"] and "?v=" not in a["url"]
    pending = {a["id"]}
    monkeypatch.setattr(multimodal, "is_pending", lambda i: i in pending)
    assert client.get(f"/api/assets/{a['id']}").json()["status"] == "pending"
    mm._update_row(a["id"], "/api/static/assets/real_new.png", "dashscope", None)  # 模拟后台原地升级
    pending.clear()
    b = client.get(f"/api/assets/{a['id']}?wait=2").json()
    assert b["id"] == a["id"] and b["status"] == "ready" and b["version"] == 2 and b["source"] == "dashscope"
    assert b["url"] != a["url"] and b["url"].endswith("?v=2")
    assert next(x for x in client.get(f"/api/worlds/{wid}/assets").json() if x["id"] == a["id"])["version"] == 2
    assert client.get("/api/assets/nope").status_code == 404


def test_pending_asset_upgrade_is_pushed_in_turn_stream(client, monkeypatch):
    from app import multimodal
    from app.config import get_settings
    from app.multimodal import assets as mm
    wid = make_world(client)
    a = _asset(client, wid)
    pending = {a["id"]}
    monkeypatch.setattr(multimodal, "is_pending", lambda i: i in pending)
    monkeypatch.setattr(multimodal, "pending_ids", lambda: list(pending))
    monkeypatch.setattr(get_settings(), "stream_delay", 0.01)
    orig = multimodal.key_scene_assets

    async def ks(*args, **kw):  # 回合内关键场景媒体期间完成"后台升级"
        mm._update_row(a["id"], "/api/static/assets/real_up.png", "dashscope", None)
        pending.clear()
        return await orig(*args, **kw)
    monkeypatch.setattr(multimodal, "key_scene_assets", ks)
    ev = sse(client, f"/api/worlds/{wid}/turns", {"action": "四处看看"})
    names = [n for n, _ in ev]
    ups = [d for n, d in ev if n == "asset" and d["id"] == a["id"]]
    assert ups and ups[-1]["status"] == "ready" and ups[-1]["version"] == 2
    assert max(i for i, n in enumerate(names) if n == "asset") < names.index("done")


def test_input_review_flag_aborts_turn(client, monkeypatch):
    from app import safety
    from app.config import get_settings
    from app.schemas import SafetyResult
    wid = make_world(client)
    monkeypatch.setattr(get_settings(), "stream_delay", 0.01)

    async def fast(text, *, minor_mode=False, rating="teen", context="turn", on_flag=None):
        async def review():
            await asyncio.sleep(0.15)
            r = SafetyResult(allowed=False, blocked=True, categories=["violence"], message="内容未通过安全审核")
            on_flag(r)
            return r
        return SafetyResult(), asyncio.ensure_future(review())
    monkeypatch.setattr(safety, "check_input_fast", fast)
    ev = sse(client, f"/api/worlds/{wid}/turns", {"action": "四处看看"})
    assert first(ev, "safety")["blocked"] and first(ev, "done") == {"blocked": True}
    assert client.get(f"/api/worlds/{wid}/turns").json() == []


def test_post_commit_review_replaces_narration(client, monkeypatch):
    from app import safety
    from app.schemas import SafetyResult
    wid = make_world(client)

    def review(text, *, minor_mode=False, rating="teen", on_flag=None, **kw):
        on_flag(SafetyResult(allowed=False, blocked=True, filtered_text="【该段内容已被安全复核替换】"))
        return None
    monkeypatch.setattr(safety, "review_output", review)
    sse(client, f"/api/worlds/{wid}/turns", {"action": "四处看看"})
    t = client.get(f"/api/worlds/{wid}/turns").json()[-1]
    assert t["narration"] == "【该段内容已被安全复核替换】"
