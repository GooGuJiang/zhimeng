"""Unit tests for app.multimodal. Fallback mode makes zero remote calls; the DashScope paths are exercised
with httpx.MockTransport (no real network)."""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import struct
import wave
import zlib
from io import BytesIO

import httpx
import pytest

from app import multimodal
from zm_unit_helpers import FAKE_KEY, install_transport


def run(coro):
    return asyncio.run(coro)


def _file(env, asset):
    assert asset.url.startswith("/api/static/assets/")
    return env.assets_dir / asset.url.rsplit("/", 1)[1]


def _png() -> bytes:
    ihdr = b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + ihdr + struct.pack(">I", zlib.crc32(ihdr))
            + struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND")))


def _wav() -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000), w.writeframes(b"\x01\x00" * 2400)
    return buf.getvalue()


# ---------- contract ----------
def test_signatures_match_team_md():
    p = inspect.signature(multimodal.illustrate).parameters
    assert list(p)[:5] == ["world_id", "prompt", "turn_id", "style", "force"]
    p = inspect.signature(multimodal.speak).parameters
    assert list(p)[:5] == ["world_id", "text", "voice", "turn_id", "force"]
    assert inspect.iscoroutinefunction(multimodal.regenerate)
    assert not inspect.iscoroutinefunction(multimodal.list_assets)


# ---------- fallback mode (ZM_FORCE_FALLBACK=1) ----------
def test_fallback_zero_remote_calls(env, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("no network in fallback mode")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    img = run(multimodal.illustrate("w1", "民国上海外滩夜景，报社记者", turn_id="t1"))
    assert img.type == "image" and img.source == "fallback" and img.turn_id == "t1"
    svg = _file(env, img).read_bytes()
    assert svg.startswith(b"<svg") and "内容由AI生成".encode() in svg
    aud = run(multimodal.speak("w1", "夜色笼罩着外滩。"))
    assert aud.type == "audio" and aud.source == "fallback" and aud.prompt == "夜色笼罩着外滩。"
    with wave.open(str(_file(env, aud))) as w:
        assert w.getnframes() > 0


def test_fallback_cache_and_regenerate(env):
    a = run(multimodal.illustrate("w1", "外滩夜景"))
    b = run(multimodal.illustrate("w1", "外滩夜景"))
    assert a.id == b.id, "cached by prompt"
    c = run(multimodal.illustrate("w1", "外滩夜景", force=True))
    assert c.id != a.id and c.url != a.url, "force bypasses cache with a new file"
    r = run(multimodal.regenerate(a.id))
    assert r and r.id != a.id and r.url != a.url and r.type == "image" and r.prompt == a.prompt
    t1 = run(multimodal.speak("w1", "你好"))
    assert run(multimodal.speak("w1", "你好")).id == t1.id
    t2 = run(multimodal.regenerate(t1.id))
    assert t2 and t2.type == "audio" and t2.id != t1.id and t2.prompt == t1.prompt
    assert run(multimodal.regenerate("ast_missing")) is None
    ids = [x.id for x in multimodal.list_assets("w1")]
    assert set(ids) >= {a.id, c.id, r.id, t1.id, t2.id} and multimodal.list_assets("other") == []


def test_style_changes_cache_key(env):
    a = run(multimodal.illustrate("w1", "外滩", style="水墨"))
    b = run(multimodal.illustrate("w1", "外滩", style="油画"))
    assert a.id != b.id


def test_prompt_sanitized(env):
    a = run(multimodal.illustrate("w1", "血腥的码头，尸块"))
    assert "血腥" not in a.prompt and "尸块" not in a.prompt


def test_voice_casting():
    from app.multimodal import voices

    assert voices.voice_for(None) == voices.NARRATOR_VOICE == voices.voice_for("narrator")
    a = voices.voice_for({"name": "阿四", "role": "码头线人，男"})
    assert a == voices.voice_for({"name": "阿四", "role": "码头线人，男"}), "stable by name"
    assert a != voices.NARRATOR_VOICE
    female, male = voices.pools()
    assert a in male
    assert voices.voice_for({"name": "白玫瑰", "role": "歌女"}) in female
    assert voices.voice_for("Ethan") == "Ethan"
    f3, m3 = voices.pools("qwen3-tts-flash")
    assert "Cherry" in f3 and "Ethan" in m3 and len(m3) > 1
    assert voices.pools("qwen-tts") == voices.pools("qwen3-tts-flash"), "qwen-tts is aliased (BUG-002)"


def test_key_scene_helpers(env):
    assert multimodal.is_key_scene(1) and not multimodal.is_key_scene(3, [])
    assert multimodal.is_key_scene(3, [{"type": "injected"}])
    p = multimodal.build_scene_prompt({"era": "民国", "genre": "侦探"}, "雨夜的外滩", "外滩", minor_mode=True)
    assert "民国" in p and "外滩" in p and len(p) <= 500
    res = run(multimodal.key_scene_assets({"id": "w2"}, "雨夜的外滩。", turn_id="t1"))
    assert [a.type for a in res] == ["image"], "auto audio is skipped (not a silent placeholder) without TTS"


# ---------- remote path (mocked DashScope) ----------
def _dashscope_handler(state):
    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if u.endswith("/services/aigc/text2image/image-synthesis"):
            state["create"] = json.loads(req.content)
            state["create_headers"] = dict(req.headers)
            return httpx.Response(200, json={"output": {"task_id": "task-1", "task_status": "PENDING"}})
        if u.endswith("/tasks/task-1"):
            state["polls"] = state.get("polls", 0) + 1
            if state["polls"] < 2:
                return httpx.Response(200, json={"output": {"task_id": "task-1", "task_status": "RUNNING"}})
            return httpx.Response(200, json={"output": {"task_status": "SUCCEEDED",
                                                        "results": [{"url": "https://oss.example/img.png"}]}})
        if u == "https://oss.example/img.png":
            assert "authorization" not in {k.lower() for k in req.headers}, "key must not leak to OSS"
            return httpx.Response(200, content=_png())
        if u.endswith("/services/aigc/multimodal-generation/generation"):
            state["tts"] = json.loads(req.content)
            return httpx.Response(200, json={"output": {"audio": {"url": "https://oss.example/a.wav"}}})
        if u == "https://oss.example/a.wav":
            return httpx.Response(200, content=_wav())
        return httpx.Response(404, json={"code": "NotFound"})
    return handler


def test_remote_image_async_task(remote, monkeypatch):
    state: dict = {}
    seen = install_transport(monkeypatch, _dashscope_handler(state))
    a = run(multimodal.illustrate("w1", "外滩夜景，报社记者"))
    assert a.source == "dashscope"
    assert state["create_headers"]["x-dashscope-async"] == "enable"
    assert state["create_headers"]["authorization"] == f"Bearer {FAKE_KEY}"
    assert state["create"]["model"] == remote.image_model and state["create"]["parameters"]["n"] == 1
    assert state["polls"] == 2
    data = _file(remote, a).read_bytes()
    assert data.startswith(b"\x89PNG") and b"AIGC" in data, "implicit AI label embedded"
    n = len(seen)
    b = run(multimodal.illustrate("w1", "外滩夜景，报社记者"))
    assert b.id == a.id and len(seen) == n, "cache hit → no new remote call"
    c = run(multimodal.illustrate("w9", "外滩夜景，报社记者"))
    assert c.world_id == "w9" and c.url == a.url and len(seen) == n, "cross-world reuse without re-billing"
    r = run(multimodal.regenerate(a.id))
    assert r.source == "dashscope" and r.url != a.url and len(seen) > n


def test_remote_tts(remote, monkeypatch):
    state: dict = {}
    install_transport(monkeypatch, _dashscope_handler(state))
    a = run(multimodal.speak("w1", "夜色笼罩着外滩。", voice="Ethan"))
    assert a.source == "dashscope" and state["tts"]["model"] == "qwen3-tts-flash"
    assert state["tts"]["input"] == {"text": "夜色笼罩着外滩。", "voice": "Ethan", "language_type": "Chinese"}
    assert _file(remote, a).read_bytes().startswith(b"RIFF")
    r = run(multimodal.regenerate(a.id))
    assert r.source == "dashscope" and state["tts"]["input"]["voice"] == "Ethan", "regenerate keeps the voice"
    # NPC by name → stable non-narrator voice
    run(multimodal.speak("w1", "跟我来。", voice="阿四"))
    assert state["tts"]["input"]["voice"] != multimodal.NARRATOR_VOICE


def test_remote_tts_base64(remote, monkeypatch):
    raw = _wav()

    def handler(req):
        return httpx.Response(200, json={"output": {"audio": {"data": base64.b64encode(raw).decode()}}})

    install_transport(monkeypatch, handler)
    a = run(multimodal.speak("w1", "测试"))
    assert a.source == "dashscope" and _file(remote, a).read_bytes() == raw


@pytest.mark.parametrize("failure", ["http500", "task_failed", "inspection", "exception", "no_url"])
def test_remote_failures_fall_back_and_never_leak_key(remote, monkeypatch, caplog, failure):
    def handler(req: httpx.Request) -> httpx.Response:
        if failure == "http500":
            return httpx.Response(500, json={"code": "InternalError", "message": f"oops {FAKE_KEY}"})
        if failure == "exception":
            raise httpx.ConnectError("boom")
        if failure == "inspection":
            return httpx.Response(400, json={"code": "DataInspectionFailed", "message": "bad"})
        if str(req.url).endswith("image-synthesis"):
            return httpx.Response(200, json={"output": {"task_id": "task-1"}})
        if failure == "no_url":
            return httpx.Response(200, json={"output": {"task_status": "SUCCEEDED", "results": []}})
        return httpx.Response(200, json={"output": {"task_status": "FAILED", "code": "X", "message": "m"}})

    install_transport(monkeypatch, handler)
    caplog.set_level(logging.DEBUG)
    img = run(multimodal.illustrate("w1", "外滩"))
    aud = run(multimodal.speak("w1", "外滩"))
    assert img.source == "fallback" and _file(remote, img).exists()
    assert aud.source == "fallback" and _file(remote, aud).exists()
    assert FAKE_KEY not in caplog.text
    # within RETRY_AFTER the failing prompt is not re-sent (no hammering a broken API)
    from app.multimodal import assets

    seen = install_transport(monkeypatch, _dashscope_handler({}))
    again = run(multimodal.illustrate("w1", "外滩"))
    assert again.id == img.id and not seen
    # after the cool-down the placeholder row is retried and upgraded in place (BUG-005)
    assets._recent_fail.clear()
    up = run(multimodal.illustrate("w1", "外滩"))
    assert up.id == img.id and up.source == "dashscope" and up.url != img.url


def test_poll_timeout(remote, monkeypatch):
    from app.multimodal import dashscope_api as ds

    monkeypatch.setattr(ds, "POLL_TIMEOUT", 0.0)

    def handler(req):
        if str(req.url).endswith("image-synthesis"):
            return httpx.Response(200, json={"output": {"task_id": "task-1"}})
        return httpx.Response(200, json={"output": {"task_status": "RUNNING"}})

    install_transport(monkeypatch, handler)
    assert run(multimodal.illustrate("w1", "外滩")).source == "fallback"


def test_redact(remote):
    from app.multimodal import dashscope_api as ds

    assert FAKE_KEY not in ds.redact(f"Bearer {FAKE_KEY}")
    assert "sk-***" in ds.redact("token sk-abcdefghijklmnop")
    assert FAKE_KEY not in str(ds.DashScopeError("X", f"msg {FAKE_KEY}"))


def test_db_failure_never_raises(env, monkeypatch):
    from app.multimodal import assets

    def broken(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(assets, "_save", broken)
    a = run(multimodal.illustrate("w1", "外滩"))
    b = run(multimodal.speak("w1", "外滩"))
    assert a.source == b.source == "fallback" and a.type == "image" and b.type == "audio"


# ---------- regression: BUG-005 (fallback assets must be cached per cache_key, upgraded in place) ----------
def _rows(world_id):
    from sqlmodel import select

    from app.db import AssetRow, session_scope
    with session_scope() as s:
        return s.exec(select(AssetRow).where(AssetRow.world_id == world_id)).all()


def test_bug005_fallback_illustrate_and_speak_are_cached(env):
    a = [run(multimodal.illustrate("w5", "民国上海外滩夜景")) for _ in range(3)]
    t = [run(multimodal.speak("w5", "夜色笼罩着外滩。")) for _ in range(3)]
    assert len({x.id for x in a}) == 1 and len({x.id for x in t}) == 1
    assert len(_rows("w5")) == 2, "no row growth for repeated identical requests"
    assert len(multimodal.list_assets("w5")) == 2


def test_bug005_fallback_row_upgraded_when_key_available(env, monkeypatch):
    img = run(multimodal.illustrate("w5", "外滩"))
    aud = run(multimodal.speak("w5", "外滩"))
    assert img.source == aud.source == "fallback"
    # a key becomes available → same rows are upgraded in place, no new rows
    env.dashscope_api_key = FAKE_KEY
    env.force_fallback = False
    from app.multimodal import dashscope_api as ds
    monkeypatch.setattr(ds, "POLL_INTERVAL", 0.0)
    install_transport(monkeypatch, _dashscope_handler({}))
    img2 = run(multimodal.illustrate("w5", "外滩"))
    aud2 = run(multimodal.speak("w5", "外滩"))
    assert (img2.id, img2.source) == (img.id, "dashscope") and img2.url != img.url
    assert (aud2.id, aud2.source) == (aud.id, "dashscope") and aud2.url != aud.url
    assert len(_rows("w5")) == 2
    assert run(multimodal.illustrate("w5", "外滩")).id == img.id  # now a real cache hit


# ---------- regression: BUG-002 (qwen-tts → qwen3-tts-flash) ----------
def test_bug002_qwen_tts_is_mapped(remote, monkeypatch):
    state: dict = {}
    install_transport(monkeypatch, _dashscope_handler(state))
    remote.tts_model = "qwen-tts"
    a = run(multimodal.speak("w1", "你好。", voice="Cherry"))
    assert a.source == "dashscope" and state["tts"]["model"] == "qwen3-tts-flash"


def test_bug002_model_not_exist_retries_with_qwen3(remote, monkeypatch):
    from app.multimodal import dashscope_api as ds

    remote.tts_model = "qwen-tts-old-custom"
    models: list[str] = []

    def handler(req):
        u = str(req.url)
        if u.endswith("/multimodal-generation/generation"):
            m = json.loads(req.content)["model"]
            models.append(m)
            if m != "qwen3-tts-flash":
                return httpx.Response(404, json={"code": "InvalidParameter", "message": "Model not exist."})
            return httpx.Response(200, json={"output": {"audio": {"url": "https://oss.example/a.wav"}}})
        return httpx.Response(200, content=_wav())

    install_transport(monkeypatch, handler)
    a = run(multimodal.speak("w1", "你好。"))
    assert a.source == "dashscope" and models == ["qwen-tts-old-custom", "qwen3-tts-flash"]
    assert ds.effective_tts_model() == "qwen3-tts-flash"  # sticky: later calls skip the dead model
    run(multimodal.speak("w1", "再见。"))
    assert models[-1] == "qwen3-tts-flash" and len(models) == 3


def test_connect_errors_are_retried(remote, monkeypatch):
    from app.multimodal import dashscope_api as ds

    monkeypatch.setattr(ds.asyncio, "sleep", _nosleep)
    n = {"c": 0}
    base = _dashscope_handler({})

    def handler(req):
        if str(req.url).endswith("/multimodal-generation/generation") and n["c"] < 2:
            n["c"] += 1
            raise httpx.ConnectTimeout("")
        return base(req)

    install_transport(monkeypatch, handler)
    assert run(multimodal.speak("w1", "重试测试。")).source == "dashscope" and n["c"] == 2


async def _nosleep(*a, **kw):
    return None


def test_http_result_url_upgraded_to_https(remote, monkeypatch):
    """TTS returns http:// OSS URLs; port 80 is often blocked → download via https first."""
    got: list[str] = []

    def handler(req):
        u = str(req.url)
        if u.endswith("/multimodal-generation/generation"):
            return httpx.Response(200, json={"output": {"audio": {
                "url": "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/x.wav?Expires=1&Signature=s"}}})
        got.append(u)
        assert "authorization" not in {k.lower() for k in req.headers}
        return httpx.Response(200, content=_wav())

    install_transport(monkeypatch, handler)
    assert run(multimodal.speak("w1", "外滩。")).source == "dashscope"
    assert got == ["https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/x.wav?Expires=1&Signature=s"]


def test_fix_wav_header():
    from app.multimodal.fallback import fix_wav_header

    good = _wav()
    bad = bytearray(good)
    bad[4:8] = struct.pack("<I", 0xFFFFFFFF)
    bad[40:44] = struct.pack("<I", 0xFFFFFFFF)
    fixed = fix_wav_header(bytes(bad))
    assert fixed == good
    with wave.open(BytesIO(fixed)) as w:
        assert w.getnframes() == 2400
    assert fix_wav_header(b"junk") == b"junk"


# ---------- deadline: placeholder now, same row upgraded in the background ----------
def _slow_image_handler(state, polls_before_done=5, fail=False):
    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if u.endswith("/image-synthesis"):
            state["creates"] = state.get("creates", 0) + 1
            return httpx.Response(200, json={"output": {"task_id": "task-1"}})
        if u.endswith("/tasks/task-1"):
            state["polls"] = state.get("polls", 0) + 1
            if state["polls"] < polls_before_done:
                return httpx.Response(200, json={"output": {"task_status": "RUNNING"}})
            if fail:
                return httpx.Response(200, json={"output": {"task_status": "FAILED", "code": "X"}})
            return httpx.Response(200, json={"output": {"task_status": "SUCCEEDED",
                                                        "results": [{"url": "https://oss.example/img.png"}]}})
        if u.endswith("/multimodal-generation/generation"):
            return httpx.Response(200, json={"output": {"audio": {"url": "https://oss.example/a.wav"}}})
        if u.endswith("a.wav"):
            return httpx.Response(200, content=_wav())
        return httpx.Response(200, content=_png())
    return handler


def test_deadline_returns_placeholder_then_upgrades_same_row(remote, monkeypatch):
    from app.multimodal import dashscope_api as ds

    monkeypatch.setattr(ds, "POLL_INTERVAL", 0.02)
    state: dict = {}
    install_transport(monkeypatch, _slow_image_handler(state, polls_before_done=6))

    async def flow():
        a = await multimodal.illustrate("w1", "外滩夜景", deadline=0.01)
        assert a.source == "fallback" and multimodal.is_pending(a.id) and a.id in multimodal.pending_ids()
        assert _file(remote, a).read_bytes().startswith(b"<svg")
        b = await multimodal.illustrate("w1", "外滩夜景", deadline=0.01)  # same request while pending
        assert b.id == a.id and state["creates"] == 1, "no second provider task while pending"
        up = await multimodal.wait_for_asset(a.id, timeout=5)
        return a, up

    a, up = run(flow())
    assert up.id == a.id and up.source == "dashscope" and up.url != a.url and up.url.endswith(".png")
    assert not multimodal.is_pending(a.id)
    assert [x.id for x in multimodal.list_assets("w1")] == [a.id], "upgraded in place, no extra row"
    assert multimodal.get_asset(a.id).source == "dashscope"


def test_deadline_not_hit_returns_real_asset(remote, monkeypatch):
    install_transport(monkeypatch, _slow_image_handler({}, polls_before_done=1))
    a = run(multimodal.illustrate("w1", "外滩夜景", deadline=5))
    assert a.source == "dashscope"


def test_deadline_speak_and_regenerate(remote, monkeypatch):
    from app.multimodal import dashscope_api as ds

    async def slow_tts(text, voice, model=None, language_type="Chinese"):
        await asyncio.sleep(0.1)
        return _wav()

    monkeypatch.setattr(ds, "text_to_speech", slow_tts)

    async def flow():
        a = await multimodal.speak("w1", "夜色笼罩着外滩。", deadline=0.01)
        assert a.source == "fallback"
        await multimodal.drain_background(5)
        up = multimodal.get_asset(a.id)
        r = await multimodal.regenerate(a.id, deadline=0.01)
        assert r.id != a.id and r.source == "fallback"
        await multimodal.drain_background(5)
        return a, up, multimodal.get_asset(r.id)

    a, up, r = run(flow())
    assert up.id == a.id and up.source == "dashscope"
    assert r.source == "dashscope" and r.url != up.url


def test_deadline_background_failure_keeps_placeholder(remote, monkeypatch, caplog):
    install_transport(monkeypatch, _slow_image_handler({}, polls_before_done=3, fail=True))

    async def flow():
        a = await multimodal.illustrate("w1", "外滩夜景", deadline=0.0)
        await multimodal.drain_background(5)
        return a

    a = run(flow())
    cur = multimodal.get_asset(a.id)
    assert cur.source == "fallback" and cur.url == a.url and not multimodal.is_pending(a.id)
    assert FAKE_KEY not in caplog.text


def test_no_deadline_is_backward_compatible(remote, monkeypatch):
    install_transport(monkeypatch, _slow_image_handler({}, polls_before_done=3))
    assert run(multimodal.illustrate("w1", "外滩夜景")).source == "dashscope"


# ---------- network robustness ----------
def test_fresh_connection_per_request_no_keepalive(remote, monkeypatch):
    seen = install_transport(monkeypatch, _slow_image_handler({}, polls_before_done=3))
    made = []
    factory = httpx.AsyncClient

    def spy(*a, **kw):
        made.append(kw)
        return factory(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", spy)
    assert run(multimodal.illustrate("w1", "外滩")).source == "dashscope"
    assert len(made) == len(seen) >= 5, "one client per request (no pooled long-lived connection)"
    assert all(k["limits"].max_keepalive_connections == 0 for k in made)
    assert all(r.headers.get("connection") == "close" for r in seen)


def test_poll_get_retried_on_read_errors(remote, monkeypatch):
    state = {"broken": 0}
    base = _slow_image_handler({}, polls_before_done=2)

    def handler(req):
        if str(req.url).endswith("/tasks/task-1") and state["broken"] < 2:
            state["broken"] += 1
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        if str(req.url).endswith("img.png") and state["broken"] < 3:
            state["broken"] += 1
            raise httpx.ReadError("connection reset")
        return base(req)

    install_transport(monkeypatch, handler)
    assert run(multimodal.illustrate("w1", "外滩")).source == "dashscope" and state["broken"] == 3


def test_poll_tolerates_transient_429(remote, monkeypatch):
    n = {"p": 0}
    base = _slow_image_handler({}, polls_before_done=1)

    def handler(req):
        if str(req.url).endswith("/tasks/task-1") and n["p"] < 2:
            n["p"] += 1
            return httpx.Response(429, json={"code": "Throttling", "message": "rate"})
        return base(req)

    install_transport(monkeypatch, handler)
    assert run(multimodal.illustrate("w1", "外滩")).source == "dashscope"


@pytest.mark.parametrize("err,expected_posts,source", [
    (httpx.ReadError("reset after send"), 1, "fallback"),      # may have been received → never re-POST (billing)
    (httpx.RemoteProtocolError("disconnected"), 1, "fallback"),
    (httpx.ReadTimeout("slow"), 1, "fallback"),
    (httpx.ConnectError("refused"), 2, "dashscope"),           # provably not sent → safe to retry
])
def test_billed_post_retried_only_when_not_sent(remote, monkeypatch, err, expected_posts, source):
    state = {"posts": 0}
    base = _slow_image_handler({}, polls_before_done=1)

    def handler(req):
        if str(req.url).endswith("/image-synthesis"):
            state["posts"] += 1
            if state["posts"] == 1:
                raise err
        return base(req)

    install_transport(monkeypatch, handler)
    a = run(multimodal.illustrate("w1", "外滩"))
    assert state["posts"] == expected_posts and a.source == source


def test_tts_post_not_resent_after_read_error(remote, monkeypatch):
    posts = {"n": 0}

    def handler(req):
        if str(req.url).endswith("/multimodal-generation/generation"):
            posts["n"] += 1
            raise httpx.ReadError("reset")
        return httpx.Response(200, content=_wav())

    install_transport(monkeypatch, handler)
    assert run(multimodal.speak("w1", "外滩。")).source == "fallback" and posts["n"] == 1


def test_retry_backoff_is_exponential_and_bounded(remote, monkeypatch):
    from app.multimodal import dashscope_api as ds

    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(ds, "BACKOFF_BASE", 0.5)
    monkeypatch.setattr(ds.asyncio, "sleep", fake_sleep)

    def handler(req):
        raise httpx.ConnectError("down")

    install_transport(monkeypatch, handler)
    with pytest.raises(httpx.ConnectError):
        run(ds._request("GET", "https://dashscope.aliyuncs.com/api/v1/tasks/x"))
    assert sleeps == [0.5, 1.0, 2.0][:ds.NET_RETRIES]


# ---------- ZM_DISABLE_IMAGE (Settings.disable_image / image_enabled, owned by config.py) ----------
def _count_requests(monkeypatch, base=None):
    seen = install_transport(monkeypatch, base or _slow_image_handler({}, polls_before_done=1))
    return seen


def test_disable_image_env_parsed_by_config(env, monkeypatch):
    from app.config import get_settings

    for val, expected in [("1", True), ("true", True), ("yes", True), ("0", False), ("", False)]:
        monkeypatch.setenv("ZM_DISABLE_IMAGE", val)
        get_settings.cache_clear()
        assert bool(getattr(get_settings(), "disable_image", False)) is expected
    monkeypatch.delenv("ZM_DISABLE_IMAGE")
    get_settings.cache_clear()


def test_disable_image_no_remote_calls_cache_and_regen(remote, monkeypatch):
    remote.disable_image = True
    seen = _count_requests(monkeypatch)
    a = run(multimodal.illustrate("w1", "外滩夜景"))
    b = run(multimodal.illustrate("w1", "外滩夜景", deadline=0.0))
    assert a.source == b.source == "fallback" and a.id == b.id and _file(remote, a).read_bytes().startswith(b"<svg")
    r = run(multimodal.regenerate(a.id))
    assert r.source == "fallback" and r.id != a.id
    assert not any("image-synthesis" in str(q.url) or "/tasks/" in str(q.url) for q in seen) and seen == []
    assert len([x for x in multimodal.list_assets("w1") if x.type == "image"]) == 2  # a + regenerate, no dupes
    st = multimodal.status()
    assert st["images"]["disabled_by_env"] and not st["images"]["enabled"]


def test_disable_image_keeps_tts_remote(remote, monkeypatch):
    remote.disable_image = True
    install_transport(monkeypatch, _dashscope_handler({}))
    assert run(multimodal.speak("w1", "夜色笼罩着外滩。")).source == "dashscope"
    assert multimodal.status()["tts"]["enabled"]


def test_disable_image_never_upgrades_existing_fallback_rows(remote, monkeypatch):
    install_transport(monkeypatch, _slow_image_handler({}, polls_before_done=1))
    real = run(multimodal.illustrate("w9", "外滩夜景"))  # a real file exists in another world
    assert real.source == "dashscope"
    remote.disable_image = True
    seen = _count_requests(monkeypatch)
    fb = run(multimodal.illustrate("w1", "外滩夜景"))
    assert fb.source == "fallback" and seen == [], "no cross-world reuse / upgrade while the switch is on"
    again = run(multimodal.illustrate("w1", "外滩夜景"))
    assert again.id == fb.id and again.source == "fallback" and again.url == fb.url


def test_disable_image_stops_running_background_job(remote, monkeypatch):
    from app.multimodal import dashscope_api as ds

    monkeypatch.setattr(ds, "POLL_INTERVAL", 0.01)
    after_flip: list[str] = []
    state = {"polls": 0}

    def handler(req):
        u = str(req.url)
        if remote.disable_image:
            after_flip.append(u)
        if u.endswith("/image-synthesis"):
            return httpx.Response(200, json={"output": {"task_id": "task-1"}})
        if u.endswith("/tasks/task-1"):
            state["polls"] += 1
            remote.disable_image = True  # switch turned on while the job is polling
            return httpx.Response(200, json={"output": {"task_status": "RUNNING"}})
        return httpx.Response(200, content=_png())

    install_transport(monkeypatch, handler)

    async def flow():
        a = await multimodal.illustrate("w1", "外滩夜景", deadline=0.0)
        await multimodal.drain_background(5)
        return a

    a = run(flow())
    assert after_flip == [] and state["polls"] == 1
    cur = multimodal.get_asset(a.id)
    assert cur.source == "fallback" and not multimodal.is_pending(a.id)


def test_force_fallback_and_disable_image_same_semantics(env):
    env.disable_image = True  # with ZM_FORCE_FALLBACK too: cached placeholder, no dupes
    a = run(multimodal.illustrate("w1", "外滩"))
    assert run(multimodal.illustrate("w1", "外滩")).id == a.id and a.source == "fallback"


# ---------- TTS: network failure → placeholder now, delayed background retry, same row upgraded ----------
def _tts_handler(fail_times: int, err, counter: dict):
    def handler(req):
        u = str(req.url)
        if u.endswith("/multimodal-generation/generation"):
            counter["posts"] = counter.get("posts", 0) + 1
            if counter["posts"] <= fail_times:
                if isinstance(err, httpx.Response):
                    return err
                raise err
            return httpx.Response(200, json={"output": {"audio": {"url": "https://oss.example/a.wav"}}})
        return httpx.Response(200, content=_wav())
    return handler


def _row(asset_id):
    from app.db import AssetRow, session_scope
    with session_scope() as s:
        return s.get(AssetRow, asset_id)


@pytest.mark.parametrize("err", [httpx.ReadError("reset"), httpx.RemoteProtocolError("disconnected"),
                                 httpx.ReadTimeout("slow"),
                                 httpx.Response(503, json={"code": "ServiceUnavailable", "message": "x"})])
def test_tts_network_error_background_retry_upgrades_same_row(remote, monkeypatch, err):
    from app.multimodal import assets

    monkeypatch.setattr(assets, "TTS_BG_DELAY", 0.01)
    c: dict = {}
    install_transport(monkeypatch, _tts_handler(1, err, c))

    async def flow():
        a = await multimodal.speak("w1", "夜色笼罩着外滩。")
        assert a.source == "fallback" and multimodal.is_pending(a.id)
        up = await multimodal.wait_for_asset(a.id, timeout=5)
        return a, up

    a, up = run(flow())
    assert up.id == a.id and up.source == "dashscope" and up.url != a.url and c["posts"] == 2
    assert not multimodal.is_pending(a.id)
    assert len(multimodal.list_assets("w1")) == 1, "upgraded in place, no new row"
    row = _row(a.id)
    if hasattr(row, "version"):  # db.py before_update listener (ORM update, not delete/re-create)
        assert row.version == 2 and row.updated_at is not None


def test_tts_background_retry_is_bounded(remote, monkeypatch):
    from app.multimodal import assets

    monkeypatch.setattr(assets, "TTS_BG_DELAY", 0.01)
    c: dict = {}
    install_transport(monkeypatch, _tts_handler(99, httpx.ReadTimeout("slow"), c))

    async def flow():
        a = await multimodal.speak("w1", "外滩。")
        await multimodal.drain_background(5)
        return a

    a = run(flow())
    assert c["posts"] == 1 + assets.TTS_BG_RETRIES, "at most 1 + N POSTs even if each may have been billed"
    assert multimodal.get_asset(a.id).source == "fallback" and not multimodal.is_pending(a.id)


@pytest.mark.parametrize("resp", [
    httpx.Response(400, json={"code": "DataInspectionFailed", "message": "bad"}),
    httpx.Response(400, json={"code": "InvalidParameter", "message": "voice"}),
    httpx.Response(429, json={"code": "Throttling", "message": "rate"}),
])
def test_tts_4xx_errors_are_not_retried(remote, monkeypatch, resp):
    from app.multimodal import assets

    monkeypatch.setattr(assets, "TTS_BG_DELAY", 0.01)
    c: dict = {}
    install_transport(monkeypatch, _tts_handler(99, resp, c))

    async def flow():
        a = await multimodal.speak("w1", "外滩。")
        await multimodal.drain_background(5)
        return a

    a = run(flow())
    assert c["posts"] == 1 and a.source == "fallback" and not multimodal.is_pending(a.id)


def test_tts_deadline_then_network_failure_retries(remote, monkeypatch):
    from app.multimodal import assets
    from app.multimodal import dashscope_api as ds

    monkeypatch.setattr(assets, "TTS_BG_DELAY", 0.01)
    n = {"calls": 0}

    async def flaky(text, voice, model=None, language_type="Chinese"):
        n["calls"] += 1
        await asyncio.sleep(0.05)
        if n["calls"] == 1:
            raise httpx.ReadError("dropped")
        return _wav()

    monkeypatch.setattr(ds, "text_to_speech", flaky)

    async def flow():
        a = await multimodal.speak("w1", "外滩。", deadline=0.0)
        up = await multimodal.wait_for_asset(a.id, timeout=5)
        return a, up

    a, up = run(flow())
    assert up.id == a.id and up.source == "dashscope" and n["calls"] == 2


def test_tts_auto_audio_without_fallback_not_retried(remote, monkeypatch):
    from app.multimodal import assets

    c: dict = {}
    install_transport(monkeypatch, _tts_handler(99, httpx.ReadError("x"), c))
    res = run(assets.generate_tts("w1", "外滩。", speaker="narrator", allow_fallback=False))
    assert res is None and c["posts"] == 1 and multimodal.list_assets("w1") == []


def test_tts_bg_retry_stops_when_remote_disabled(remote, monkeypatch):
    from app.multimodal import assets

    monkeypatch.setattr(assets, "TTS_BG_DELAY", 0.05)
    c: dict = {}
    install_transport(monkeypatch, _tts_handler(1, httpx.ReadError("x"), c))

    async def flow():
        a = await multimodal.speak("w1", "外滩。")
        remote.force_fallback = True  # e.g. ZM_FORCE_FALLBACK toggled → background retry must not call out
        await multimodal.drain_background(5)
        return a

    a = run(flow())
    assert c["posts"] == 1 and multimodal.get_asset(a.id).source == "fallback"


def test_deadline_upgrade_bumps_version_via_orm_listener(remote, monkeypatch):
    from app.multimodal import dashscope_api as ds

    monkeypatch.setattr(ds, "POLL_INTERVAL", 0.01)
    install_transport(monkeypatch, _slow_image_handler({}, polls_before_done=3))

    async def flow():
        a = await multimodal.illustrate("w1", "外滩", deadline=0.0)
        await multimodal.drain_background(5)
        return a

    a = run(flow())
    row = _row(a.id)
    assert row.source == "dashscope"
    if hasattr(row, "version"):
        assert row.version == 2 and row.updated_at is not None
