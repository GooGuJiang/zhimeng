"""备用模型链 + 两步世界生成（用假的 OpenAI 客户端，不访问网络）。"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from test_core import first, sse

SKELETON = {"title": "雾港疑云", "genre": "民国悬疑", "tone": "阴郁", "era": "1930年代", "setting": "雾气笼罩的港口城市。",
            "initial_conflict": "歌女失踪，只留下一枚袖扣。", "player": {"name": "林墨", "role": "报社记者"},
            "locations": [{"name": "报馆", "description": "油墨味"}, {"name": "码头", "description": "汽笛"},
                          {"name": "舞厅", "description": "霓虹"}],
            "characters": [{"name": "老周", "role": "线人", "location": "码头", "emoji": "🎩"},
                           {"name": "白兰", "role": "舞女", "location": "舞厅", "emoji": "🌸"}],
            "opening_options": ["去码头", "去舞厅", "翻报纸"]}
ENRICH = {"locations": [{"id": "loc_1", "name": "报馆", "description": "打字机声不断的编辑部", "x": 20, "y": 20,
                         "connections": ["loc_2"], "interactables": ["主编抽屉"]},
                        {"id": "loc_2", "name": "码头", "description": "苦力与帮派混杂", "x": 80, "y": 30, "connections": ["loc_1", "loc_3"]}],
          "characters": [{"id": "c_1", "name": "老周", "persona": "油滑胆小、见钱眼开", "goals": ["攒钱给母亲治病"],
                          "relations": [{"target_id": "player", "type": "线人", "affinity": 30}, {"target_id": "c_2", "type": "旧识", "affinity": 10}]},
                         {"id": "c_2", "name": "白兰", "persona": "心思缜密", "goals": ["找到姐妹"]}],
          "items": [{"name": "记者证", "description": "外勤记者证", "owner_id": "player"}], "stats": {"线索": 5},
          "opening_scene": "细雨落在报馆的玻璃窗上……", "opening_options": [{"id": "opt_1", "text": "拆开匿名信"}]}


class Err(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.status_code = code


class FakeLLM:
    def __init__(self, fail=(), enrich_ok=True, enrich_delay=0.0):
        self.fail, self.enrich_ok, self.enrich_delay, self.calls = set(fail), enrich_ok, enrich_delay, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.embeddings = SimpleNamespace(create=self.embed)

    async def embed(self, **kw):
        raise Err(503, "embedding down")

    async def create(self, model, messages, stream=False, **kw):
        sys = messages[0]["content"]
        self.calls.append(model)
        if model in self.fail:
            raise Err(429, "Error code: 429 limit_requests")
        if "快速勾勒" in sys:
            text = json.dumps(SKELETON, ensure_ascii=False)
        elif "补全细节" in sys:
            if self.enrich_delay:
                import asyncio
                await asyncio.sleep(self.enrich_delay)
            if not self.enrich_ok:
                raise Err(500, "server error")
            text = json.dumps(ENRICH, ensure_ascii=False)
        elif stream:
            text = "雨夜里，你推开报馆的门，老周压低声音说：“码头出事了。”"
        else:
            text = json.dumps({"verdict": "allow", "categories": [], "rating": "all", "crisis": False}, ensure_ascii=False)
        if not stream:
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

        async def gen():
            for i in range(0, len(text), 12):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text[i:i + 12]))])
        return gen()


@pytest.fixture
def fake(core_env, monkeypatch):
    from app.config import get_settings
    from app.llm import client as llm

    s = get_settings()
    s.dashscope_api_key, s.force_fallback = "sk-test-not-real", False
    llm._cooldown.clear()
    holder = {"llm": FakeLLM()}
    monkeypatch.setattr(llm, "get_client", lambda: holder["llm"])
    yield holder
    llm._cooldown.clear()


def test_model_chain_switches_on_429(fake):
    import asyncio

    from app.llm import client as llm
    fake["llm"] = FakeLLM(fail={"qwen-plus", "qwen-plus-latest"})
    meta = {}
    out = asyncio.run(llm.chat_text([{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}], meta=meta))
    assert out and meta["model"] == "qwen-max"
    assert fake["llm"].calls[:3] == ["qwen-plus", "qwen-plus-latest", "qwen-max"]
    # 冷却中的模型排到链尾
    assert llm.model_chain("qwen-plus")[0] == "qwen-max"


def test_whole_chain_fails_returns_none(fake):
    import asyncio

    from app.llm import client as llm
    fake["llm"] = FakeLLM(fail={"qwen-plus", "qwen-plus-latest", "qwen-max", "qwen-turbo", "qwen-flash"})
    assert asyncio.run(llm.chat_text([{"role": "system", "content": "x"}])) is None


def test_stream_switches_before_first_token(fake):
    import asyncio

    from app.llm import client as llm
    fake["llm"] = FakeLLM(fail={"qwen-flash"})
    meta = {}

    async def run():
        return "".join([c async for c in llm.chat_stream([{"role": "system", "content": "快速勾勒"}], model="qwen-flash", meta=meta)])
    assert "雾港疑云" in asyncio.run(run()) and meta["model"] == "qwen-turbo"


def _wait_status(client, wid, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        w = client.get(f"/api/worlds/{wid}").json()
        if w["detail_status"] != "enriching":
            return w
        time.sleep(0.05)
    return w


def test_two_step_generation_skeleton_then_details(fake, client):
    fake["llm"] = FakeLLM(enrich_delay=0.3)
    ev = sse(client, "/api/worlds/generate", {"prompt": "民国侦探"})
    w = first(ev, "world")
    assert w["detail_status"] == "enriching" and w["source"] == "llm"
    assert [l["name"] for l in w["locations"]] == ["报馆", "码头", "舞厅"]
    assert all(c["persona"] and c["goals"] for c in w["characters"]), "骨架必须已按本地规则补齐、可玩"
    assert first(ev, "done")["detail_status"] == "enriching"
    full = _wait_status(client, w["id"])
    assert full["detail_status"] == "complete"
    laozhou = next(c for c in full["characters"] if c["name"] == "老周")
    assert laozhou["persona"] == "油滑胆小、见钱眼开" and laozhou["id"] == "c_1"
    assert full["opening_scene"].startswith("细雨落在报馆")
    assert [l["name"] for l in full["locations"]] == ["报馆", "码头", "舞厅"], "名单与预览一致"


def test_wait_details_pushes_second_world(fake, client):
    ev = sse(client, "/api/worlds/generate", {"prompt": "民国侦探", "wait_details": True})
    worlds = [d for n, d in ev if n == "world"]
    assert [w["detail_status"] for w in worlds] == ["enriching", "complete"]
    assert first(ev, "done")["detail_status"] == "complete"


def test_enrich_failure_keeps_playable_skeleton(fake, client):
    fake["llm"] = FakeLLM(enrich_ok=False)
    w = first(sse(client, "/api/worlds/generate", {"prompt": "民国侦探"}), "world")
    full = _wait_status(client, w["id"])
    assert full["detail_status"] == "local"
    client.post(f"/api/worlds/{w['id']}/confirm")
    assert first(sse(client, f"/api/worlds/{w['id']}/turns", {"action": "去码头"}), "done")


def test_skeleton_chain_all_fail_falls_back_to_template(fake, client):
    fake["llm"] = FakeLLM(fail={"qwen-flash", "qwen-turbo", "qwen-plus"})
    ev = sse(client, "/api/worlds/generate", {"prompt": "一个民国上海滩的侦探故事"})
    w = first(ev, "world")
    assert w["source"] == "fallback" and w["detail_status"] == "complete"


def test_enrich_after_play_does_not_reset_state(fake, client):
    fake["llm"] = FakeLLM(enrich_delay=0.8)
    w = first(sse(client, "/api/worlds/generate", {"prompt": "民国侦探"}), "world")
    client.post(f"/api/worlds/{w['id']}/confirm")
    first(sse(client, f"/api/worlds/{w['id']}/turns", {"action": "去码头"}), "done")
    full = _wait_status(client, w["id"])
    assert full["detail_status"] == "complete" and full["state"]["turn"] == 1
    assert next(c for c in full["characters"] if c["name"] == "老周")["persona"] == "油滑胆小、见钱眼开"
