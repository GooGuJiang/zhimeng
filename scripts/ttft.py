#!/usr/bin/env python3
"""测量运行中服务的回合首字延迟（time-to-first-token）与世界预览耗时，只读输出数字，不打印任何密钥。

    backend/.venv/bin/python scripts/ttft.py [--api http://localhost:8000] [--turns 5]
"""
import argparse, json, statistics, time, uuid

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--api", default="http://localhost:8000")
ap.add_argument("--turns", type=int, default=5)
a = ap.parse_args()
ACTIONS = ["我去码头找线人打听消息", "跟踪可疑的黄包车夫", "回报社向主编汇报", "夜访霞飞路的咖啡馆", "翻看今天的申报头版",
           "去巡捕房打听", "去百乐门舞厅"]


def stream(c, path, body):
    """返回 (首个 token 秒数|None, 首个 world 秒数|None, 总秒数, done 数据, 是否有 fallback 重置)"""
    t0 = time.time(); tok = wld = None; done = None; ev = None; reset = False
    with c.stream("POST", path, json=body, timeout=300) as r:
        for line in r.iter_lines():
            if line.startswith("event:"):
                ev = line[6:].strip()
                if ev == "token" and tok is None: tok = time.time() - t0
                if ev == "world" and wld is None: wld = time.time() - t0
            elif line.startswith("data:") and ev in ("done", "progress"):
                d = json.loads(line[5:])
                if ev == "done": done = d
                elif d.get("stage") == "fallback" and d.get("reset"): reset = True
    return tok, wld, time.time() - t0, done, reset


with httpx.Client(base_url=a.api) as c:
    h = c.get("/api/health").json()
    print(f"mode: {'fallback' if h.get('fallback') else 'real-model'}")
    _, wld, total, done, _ = stream(c, "/api/worlds/generate", {"prompt": "一个民国上海滩的侦探故事，我是报社记者"})
    print(f"world preview: {wld:.2f}s (stream total {total:.2f}s, source={done and done.get('source')})")
    wid = done["world_id"]; c.post(f"/api/worlds/{wid}/confirm")
    ttfts, srcs = [], []
    for i in range(a.turns):
        tok, _, total, done, reset = stream(c, f"/api/worlds/{wid}/turns",
                                            {"action": ACTIONS[i % len(ACTIONS)], "client_turn_id": str(uuid.uuid4())})
        src = ((done or {}).get("turn") or {}).get("source")
        srcs.append(src)
        if tok is not None: ttfts.append(tok)
        print(f"turn {i + 1}: first token {tok if tok is None else round(tok, 2)}s, total {total:.2f}s, source={src}, reset={reset}")
    if ttfts:
        print(f"TTFT median {statistics.median(ttfts):.2f}s  min {min(ttfts):.2f}s  max {max(ttfts):.2f}s  (target ≤2s)")
    print(f"turn sources: {srcs}")
