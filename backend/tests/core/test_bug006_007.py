"""BUG-006（模型链全失败/流中断 → 本地兜底并提交）与 BUG-007（非流式 LLM 端点限时 + 学习小结异步）的回归测试。
全部用假的 OpenAI 客户端模拟 429 / 断流 / 慢响应，不访问网络。"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from test_core import first, sse
from test_llm_two_step import Err, FakeLLM, fake  # noqa: F401 - fixture

ALL = {"qwen-plus", "qwen-plus-latest", "qwen-max", "qwen-turbo", "qwen-flash"}


class MidStreamBreak(FakeLLM):
    """旁白流每次都在吐出一小段后被对端断开（模拟 incomplete chunked read）。"""

    async def create(self, model, messages, stream=False, **kw):
        sys = messages[0]["content"]
        if not stream or "快速勾勒" in sys or "补全细节" in sys:
            return await super().create(model, messages, stream=stream, **kw)
        self.calls.append(model)

        async def gen():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="雨夜里你推开"))])
            raise Exception("peer closed connection without sending complete message body (incomplete chunked read)")
        return gen()


class Slow(FakeLLM):
    async def create(self, model, messages, stream=False, **kw):
        if not stream:
            await asyncio.sleep(1.0)
        return await super().create(model, messages, stream=stream, **kw)


def _no_error(ev):
    return not [d for n, d in ev if n == "error"]


def test_bug006_whole_chain_429_turn_world_and_qa_fall_back(fake, client):
    fake["llm"] = FakeLLM(fail=ALL)
    ev = sse(client, "/api/worlds/generate", {"prompt": "民国侦探"})
    w = first(ev, "world")
    assert _no_error(ev) and w["source"] == "fallback" and first(ev, "done")["source"] == "fallback"
    client.post(f"/api/worlds/{w['id']}/confirm")
    ev = sse(client, f"/api/worlds/{w['id']}/turns", {"action": "去码头找线人"})
    done = first(ev, "done")
    assert _no_error(ev) and done["turn"]["source"] == "fallback" and done["turn"]["narration"]
    assert client.get(f"/api/worlds/{w['id']}/turns").json()[-1]["source"] == "fallback"  # 已提交
    assert client.post(f"/api/worlds/{w['id']}/god/tick").status_code == 200
    r = client.post(f"/api/worlds/{w['id']}/memory/query", json={"question": "线人在哪？"})
    assert r.status_code == 200 and r.json()["answer"]


def test_bug006_stream_breaks_after_tokens_resets_and_rewrites(fake, client):
    fake["llm"] = FakeLLM(fail=ALL)
    w = first(sse(client, "/api/worlds/generate", {"prompt": "民国侦探"}), "world")
    client.post(f"/api/worlds/{w['id']}/confirm")
    fake["llm"] = MidStreamBreak()
    ev = sse(client, f"/api/worlds/{w['id']}/turns", {"action": "四处看看"})
    assert _no_error(ev)
    names = [n for n, _ in ev]
    reset_at = next(i for i, (n, d) in enumerate(ev) if n == "progress" and d.get("reset"))
    assert ev[reset_at][1]["stage"] == "fallback"
    after = "".join(d["text"] for n, d in ev[reset_at:] if n == "token")
    done = first(ev, "done")
    assert done["turn"]["source"] == "fallback"
    assert after.strip() == done["turn"]["narration"], "重置后的 token 即整段兜底旁白（以 done.turn.narration 为准）"
    assert names.index("done") > reset_at


def test_bug007_sync_llm_deadline_falls_back(fake, monkeypatch):
    from app.config import get_settings
    from app.llm import client as llm
    fake["llm"] = Slow()
    monkeypatch.setattr(get_settings(), "sync_llm_timeout_s", 0.2)
    t0 = time.time()
    out = asyncio.run(llm.chat_text([{"role": "system", "content": "x"}], deadline=0.2))
    assert out is None and time.time() - t0 < 0.8


def test_bug007_education_summary_returns_fast_then_completes(fake, client, monkeypatch):
    from app.config import get_settings
    fake["llm"] = FakeLLM(fail=ALL)
    ev = sse(client, "/api/education/generate", {"source_text": "《桃花源记》晋太元中，武陵人捕鱼为业。缘溪行，忘路之远近。"})
    wid = first(ev, "done")["world_id"]
    assert client.get(f"/api/worlds/{wid}").json()["knowledge_cards"]
    fake["llm"] = Slow()
    monkeypatch.setattr(get_settings(), "sync_llm_timeout_s", 0.2)
    t0 = time.time()
    r = client.get(f"/api/worlds/{wid}/education/summary").json()
    assert time.time() - t0 < 0.9
    assert r["status"] == "pending" and r["source"] == "fallback" and r["quiz"] and r["key_points"]  # 向后兼容字段齐全
