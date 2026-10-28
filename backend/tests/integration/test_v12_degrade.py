"""API v1.2 降级行为（BUG-006 / BUG-007）——黑盒集成测试。

兜底模式：回合 / 世界 / 小结的 `source` 字段为 "fallback"，小结 `status` 合法。
「模型全链不可用」：子进程里配置一个假 Key + 指向本机不可达端口的 DashScope 地址（不出网、确定性），
验证回合不以 `error` 结束而是用本地模板提交（done.turn.source="fallback"），学习小结 ≤ ~8s 返回。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
import warnings
from pathlib import Path

import pytest

from conftest import DEMO_PROMPT, LIVE, REAL, all_of, first

BACKEND = Path(__file__).resolve().parents[2]
SOURCE = "《桃花源记》晋太元中，武陵人捕鱼为业。缘溪行，忘路之远近。忽逢桃花林，夹岸数百步，中无杂树，芳草鲜美，落英缤纷。"


def _turn(api, wid, action):
    return api.sse(f"/api/worlds/{wid}/turns", {"action": action, "client_turn_id": str(uuid.uuid4())})


def test_v12_turn_source_and_reset_contract(api, world):
    ev = _turn(api, world["id"], "去霞飞路的咖啡馆等线人")
    assert not first(ev, "error"), first(ev, "error")
    done = first(ev, "done")
    turn = done["turn"]
    assert turn.get("source") in {"llm", "fallback"}, turn.keys()
    if not LIVE and not REAL:
        assert turn["source"] == "fallback"
    resets = [p for p in all_of(ev, "progress") if p.get("stage") == "fallback"]
    for p in resets:
        assert p.get("reset") is True and p.get("message")
    assert turn["narration"].strip(), "done.turn.narration is authoritative and non-empty"


def test_v12_education_summary_status_source(api):
    ev = api.sse("/api/education/generate", {"source_text": SOURCE, "subject": "语文"})
    wid = first(ev, "world")["id"]
    api.post(f"/api/worlds/{wid}/confirm")
    _turn(api, wid, "我沿着溪水划船前行")
    t0 = time.time()
    r = api.get(f"/api/worlds/{wid}/education/summary")
    dt = time.time() - t0
    assert r.status_code == 200, r.text[:200]
    s = r.json()
    assert s["status"] in {"complete", "pending"} and s["source"] in {"llm", "fallback"}
    assert s["key_points"] and s["quiz"], "old shape always present"
    if dt >= 12:  # 外部模型时延：软检查，只告警（验收口径：功能可用且体验可接受）
        warnings.warn(f"education summary took {dt:.1f}s (target ≤ ~8s)")
    if not LIVE and not REAL:
        assert s["source"] == "fallback" and s["status"] == "complete"
    if s["status"] == "pending":  # 后台 LLM 版本，稍后再取
        for _ in range(10):
            time.sleep(3)
            s2 = api.get(f"/api/worlds/{wid}/education/summary").json()
            if s2["status"] == "complete":
                break
        assert s2["status"] == "complete", "pending summary should complete on a later GET"


CHAIN_DOWN = textwrap.dedent(r'''
    import json, sys, time, uuid
    from fastapi.testclient import TestClient
    from app.main import app
    sys.path.insert(0, sys.argv[1])
    from conftest import parse_sse, first
    out = {}
    with TestClient(app) as c:
        me = c.get("/api/auth/me")  # feat/auth：ZM_AUTH_REQUIRED=1 时先注册登录（cookie 罐保存会话）
        if me.status_code != 404 and (me.json() or {}).get("auth_required"):
            rr = c.post("/api/auth/register", json={"username": "qadown" + uuid.uuid4().hex[:8],
                                                    "password": "Zm-QA-pass-2026!", "nickname": "QA"})
            assert rr.status_code == 201, rr.text[:200]
        def sse(path, body):
            r = c.post(path, json=body, timeout=300)
            return parse_sse(r.text)
        t0 = time.time()
        ev = sse("/api/worlds/generate", {"prompt": "一个民国上海滩的侦探故事，我是报社记者"})
        w = first(ev, "world"); out["gen_s"] = round(time.time() - t0, 1)
        out["world_source"] = w and w.get("source"); out["gen_error"] = first(ev, "error")
        wid = w["id"]; c.post(f"/api/worlds/{wid}/confirm")
        t0 = time.time()
        ev = sse(f"/api/worlds/{wid}/turns", {"action": "我去码头找线人", "client_turn_id": str(uuid.uuid4())})
        out["turn_s"] = round(time.time() - t0, 1)
        d = first(ev, "done") or {}
        out["turn_error"] = first(ev, "error"); out["turn_source"] = (d.get("turn") or {}).get("source")
        out["turn_narration_len"] = len((d.get("turn") or {}).get("narration") or "")
        t0 = time.time()
        r = c.post(f"/api/worlds/{wid}/memory/query", json={"question": "线人在哪？"})
        out["qa_status"] = r.status_code; out["qa_s"] = round(time.time() - t0, 1)
        ev = sse("/api/education/generate", {"source_text": "晋太元中，武陵人捕鱼为业。缘溪行，忘路之远近。"})
        ew = first(ev, "world")["id"]; c.post(f"/api/worlds/{ew}/confirm")
        t0 = time.time()
        s = c.get(f"/api/worlds/{ew}/education/summary")
        out["sum_s"] = round(time.time() - t0, 1); out["sum_status"] = s.status_code
        out["sum_source"] = s.json().get("source")
    print("RESULT " + json.dumps(out, ensure_ascii=False))
''')


@pytest.mark.skipif(bool(LIVE), reason="in-process only")
def test_v12_whole_model_chain_down_degrades_to_templates():
    env = {k: v for k, v in os.environ.items() if k != "DASHSCOPE_API_KEY"}
    env.update({
        "DASHSCOPE_API_KEY": "qa-dummy-not-a-real-key",       # 假 Key：只为让 llm_enabled=True
        "DASHSCOPE_BASE_URL": "http://127.0.0.1:9/v1",        # 不可达 → 每个模型都连接失败
        "DASHSCOPE_API_URL": "http://127.0.0.1:9/api/v1",
        "ZM_FORCE_FALLBACK": "0", "ZM_DATA_DIR": tempfile.mkdtemp(prefix="zm-qa-down-"), "STREAM_DELAY": "0",
    })
    p = subprocess.run([sys.executable, "-c", CHAIN_DOWN, str(Path(__file__).parent)], cwd=BACKEND, env=env,
                       capture_output=True, text=True, timeout=600)
    line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line, f"rc={p.returncode}\n{p.stderr[-2000:]}"
    r = json.loads(line[7:])
    print(r)
    assert r["world_source"] == "fallback" and not r["gen_error"], r
    assert not r["turn_error"] and r["turn_source"] == "fallback" and r["turn_narration_len"] > 0, r
    assert r["qa_status"] == 200, r
    assert r["sum_status"] == 200 and r["sum_source"] == "fallback", r
    if r["sum_s"] >= 12 or r["turn_s"] >= 20:
        warnings.warn(f"degraded path slow: turn {r['turn_s']}s, summary {r['sum_s']}s")
