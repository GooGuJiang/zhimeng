"""账号 / 鉴权 / 权限隔离（feat/auth）。

契约：API.md / TEAM.md「用户系统接口契约」与「账号/鉴权 QA 契约」（v1.4-draft2）。
- 后端未实现 /api/auth/*（GET /api/auth/me → 404）时整个模块 skip。
- 两种模式都要跑（scripts/qa.sh api 会各跑一遍）：
    默认 ZM_AUTH_REQUIRED=0：匿名请求 = 演示账号 u_demo；
    ZM_AUTH_REQUIRED=1：匿名访问受保护接口 → 401 unauthorized。
  每个模式专属的用例在另一模式下 skip（原因写明）。
- 全部在 ZM_FORCE_FALLBACK=1 + 临时 ZM_DATA_DIR 下（conftest.py），不调用远程模型/生图/配音。
- 限流隔离：每个用户/用例用独立的 X-Forwarded-For 来源 IP（进程内客户端伪装成 127.0.0.1 代理，契约 §5 采信 XFF）。
"""
from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path

import pytest

from conftest import (AUTH_PASSWORD, DEMO_PROMPT, LIVE, UserApi, auth_enabled, auth_required, cookie_values,
                      credentials, first, login_user, register_user, unique_ip, unique_name)

GEN = {"prompt": DEMO_PROMPT, "mode": "story", "language": "zh", "rating": "teen"}
EDU = {"source_text": "《桃花源记》晋太元中，武陵人捕鱼为业。缘溪行，忘路之远近。", "subject": "语文"}


def code(r) -> str | None:
    try:
        return r.json().get("code")
    except Exception:  # noqa: BLE001
        return None


def assert_404(r, what=""):
    assert r.status_code == 404, f"{what} → {r.status_code}（他人资源应 404 not_found）: {r.text[:200]}"
    assert code(r) == "not_found", f"{what}: 404 应带 code=not_found，实际 {r.text[:200]}"


def user_of(r) -> dict:
    j = r.json()
    return j.get("user") or j


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def client(make_client):
    c = make_client()
    if not auth_enabled(c):
        pytest.skip("后端尚未实现用户系统（GET /api/auth/me → 404）：等待 织梦-后端 完成 feat/auth")
    return c


@pytest.fixture(scope="module")
def required(client) -> bool:
    return auth_required(client)


def _user(client, prefix="qa") -> UserApi:
    r, name = register_user(client, unique_name(prefix))
    assert r.status_code == 201, f"register -> {r.status_code}: {r.text[:300]}"
    cred = credentials(r)
    assert cred, "注册成功应自动登录（Set-Cookie zm_access / zm_refresh）"
    return UserApi(client, cred, name, user_of(r))


@pytest.fixture(scope="module")
def alice(client) -> UserApi:
    return _user(client, "alice")


@pytest.fixture(scope="module")
def bob(client) -> UserApi:
    return _user(client, "bob")


@pytest.fixture(scope="module")
def anon(client) -> UserApi:
    return UserApi(client, {})


@pytest.fixture(scope="module")
def alice_world(alice):
    """alice 的一个已确认世界 + 1 回合 + 1 条举报 + 至少 1 个资产（兜底模式，占位资产）。"""
    r = alice.post("/api/worlds", GEN)
    assert r.status_code == 200, r.text[:300]
    w = r.json()
    wid = w["id"]
    assert alice.post(f"/api/worlds/{wid}/confirm").status_code == 200
    ev = alice.sse(f"/api/worlds/{wid}/turns", {"action": "我去码头找线人", "client_turn_id": str(uuid.uuid4())})
    done = first(ev, "done")
    assert done and done.get("turn"), [n for n, _ in ev]
    rep = alice.post("/api/reports", {"world_id": wid, "content": "QA 举报样例", "reason": "other"})
    assert rep.status_code == 200, rep.text[:200]
    assets = alice.get(f"/api/worlds/{wid}/assets").json()
    if not assets:  # 开局媒体后台生成；兜底模式下几乎即时。保险起见补一个配音占位（兜底 = 静音 WAV，不调远程）
        assets = [alice.post(f"/api/worlds/{wid}/assets/tts", {"text": "测试旁白"}).json()]
    return {"id": wid, "title": w["title"], "world": w, "turn": done["turn"], "asset_id": assets[0]["id"]}


# ======================= 注册 =======================
def test_register_201_user_and_cookies(client):
    r, name = register_user(client, unique_name("reg"), nickname="小测", email=f"{uuid.uuid4().hex[:8]}@example.com")
    assert r.status_code == 201, r.text[:300]
    u = r.json()["user"]
    assert u["username"] == name and u["id"].startswith("u_") and u["nickname"] == "小测"
    assert u["is_demo"] is False and isinstance(u.get("preferences"), dict)
    low = r.text.lower()
    assert "password" not in low and "hash" not in low and AUTH_PASSWORD.lower() not in low, "不得回显密码/哈希"
    jar = cookie_values(r)
    assert {"zm_access", "zm_refresh"} <= set(jar), f"注册后应自动登录，Set-Cookie: {list(jar)}"
    sc = [h.lower() for h in r.headers.get_list("set-cookie")] if hasattr(r.headers, "get_list") else \
        [r.headers.get("set-cookie", "").lower()]
    for h in sc:
        if h.startswith("zm_"):
            assert "httponly" in h and "samesite=lax" in h, f"cookie 属性: {h[:160]}"
    acc = next((h for h in sc if h.startswith("zm_access=")), "")
    ref = next((h for h in sc if h.startswith("zm_refresh=")), "")
    assert "path=/api" in acc, acc[:160]
    assert "path=/api/auth" in ref, ref[:160]


def test_register_duplicate_username_409(client):
    name = unique_name("dup")
    assert register_user(client, name)[0].status_code == 201
    r2, _ = register_user(client, name, password="Another-pass-123")
    assert r2.status_code == 409 and code(r2) == "username_taken", r2.text[:200]
    r3, _ = register_user(client, name.upper())  # 唯一性不区分大小写
    assert r3.status_code == 409 and code(r3) == "username_taken", r3.text[:200]


def test_register_duplicate_email_409(client):
    email = f"dup{uuid.uuid4().hex[:6]}@Example.com"
    assert register_user(client, email=email)[0].status_code == 201
    r2, _ = register_user(client, email=email.lower())
    assert r2.status_code == 409 and code(r2) == "email_taken", r2.text[:200]


@pytest.mark.parametrize("username, field_code", [
    ("ab", "validation_error"), ("_abc", "validation_error"), ("1abc", "validation_error"), ("has space", "validation_error"),
    ("a" * 21, "validation_error"), ("中文名", "validation_error"),
    ("admin", "username_reserved"), ("Demo", "username_reserved"),
])
def test_register_username_rules(client, username, field_code):
    r, _ = register_user(client, username)
    exp = 422 if field_code == "validation_error" else 400
    assert r.status_code == exp and code(r) == field_code, f"{username!r}: {r.status_code} {r.text[:200]}"
    if field_code == "validation_error":
        assert r.json().get("field") == "username", r.text[:200]


@pytest.mark.parametrize("pw, why", [("Ab1", "过短"), ("abcdefgh", "无数字"), ("12345678", "无字母"),
                                     ("SELF", "等于用户名"), ("Ab1" + "x" * 62, "超过 64 位（§13）")])
def test_register_weak_password(client, pw, why):
    name = unique_name("weak")
    r, _ = register_user(client, name, password=name if pw == "SELF" else pw)
    assert r.status_code in (400, 422) and code(r) in ("weak_password", "validation_error"), f"{why}: {r.text[:200]}"


def test_register_missing_fields_422(client):
    client.cookies.clear()
    for body in ({"password": AUTH_PASSWORD}, {"username": unique_name("nopw")}, {}):
        r = client.post("/api/auth/register", json=body, headers={"X-Forwarded-For": unique_ip()})
        assert r.status_code == 422, f"{body}: {r.status_code}"


def test_register_rate_limited_per_ip(client):
    ip = unique_ip()
    codes = [register_user(client, ip=ip)[0].status_code for _ in range(11)]
    assert codes[:10] == [201] * 10, codes
    assert codes[10] == 429, f"同一 IP 每小时注册上限 10：{codes}"


# ======================= 登录 =======================
def test_login_by_username_and_email_case_insensitive(client):
    email = f"lg{uuid.uuid4().hex[:6]}@example.com"
    _, name = register_user(client, unique_name("Login"), email=email)
    for login in (name, name.upper(), email, email.upper()):
        r = login_user(client, login)
        assert r.status_code == 200, f"login={login}: {r.status_code} {r.text[:200]}"
        assert r.json()["user"]["username"] == name
        assert {"zm_access", "zm_refresh"} <= set(cookie_values(r))
        me = UserApi(client, credentials(r)).get("/api/auth/me").json()
        assert me["authenticated"] is True and me["user"]["username"] == name


def test_login_wrong_password_and_unknown_user_same_error(client):
    _, name = register_user(client, unique_name("wrongpw"))
    bad = login_user(client, name, "Wrong-pass-999")
    unknown = login_user(client, unique_name("nobody"))
    for r in (bad, unknown):
        assert r.status_code == 401 and code(r) == "invalid_credentials", r.text[:200]
        assert not credentials(r), "登录失败不应下发会话 cookie"
    assert bad.json()["detail"] == unknown.json()["detail"], "不得区分“用户不存在”与“密码错误”"


def test_login_rate_limit_lockout(client):
    """同一 IP + 同一用户名 15 分钟内失败 5 次 → 锁 5 分钟：429 + Retry-After + retry_after；锁定期内正确密码也 429。
    其他 IP 不受影响（独立 IP 隔离，避免波及其他用例）。"""
    _, name = register_user(client, unique_name("rl"))
    ip = unique_ip()
    first5 = [login_user(client, name, "Wrong-pass-999", ip=ip).status_code for _ in range(5)]
    assert first5 == [401] * 5, first5
    locked = login_user(client, name, "Wrong-pass-999", ip=ip)
    assert locked.status_code == 429 and code(locked) == "rate_limited", locked.text[:200]
    ra = locked.headers.get("retry-after")
    assert ra and ra.isdigit() and 0 < int(ra) <= 300, f"Retry-After: {ra}"
    assert 0 < int(locked.json().get("retry_after", 0)) <= 300, locked.text[:200]
    assert login_user(client, name, ip=ip).status_code == 429, "锁定期内正确密码也应 429"
    assert login_user(client, name, ip=unique_ip()).status_code == 200, "其他 IP 不应被锁"


def test_login_success_resets_failure_counter(client):
    _, name = register_user(client, unique_name("reset"))
    ip = unique_ip()
    for _ in range(4):
        assert login_user(client, name, "Wrong-pass-999", ip=ip).status_code == 401
    assert login_user(client, name, ip=ip).status_code == 200
    for _ in range(4):
        assert login_user(client, name, "Wrong-pass-999", ip=ip).status_code == 401, "成功登录后计数应清零"


@pytest.mark.skipif(bool(LIVE), reason="读取进程内临时数据目录，仅进程内模式")
def test_password_not_stored_in_plaintext(client):
    secret = f"Plain{uuid.uuid4().hex[:12]}9"
    r, _ = register_user(client, password=secret)
    assert r.status_code == 201
    data_dir = Path(os.environ["ZM_DATA_DIR"])
    hits = [p for p in data_dir.rglob("*") if p.is_file() and p.stat().st_size < 50_000_000 and secret.encode() in p.read_bytes()]
    assert not hits, f"明文密码出现在数据文件中: {hits}"


@pytest.mark.skipif(bool(LIVE), reason="读取进程内临时数据目录，仅进程内模式")
def test_secrets_autogenerated_0600(client, anon):
    """ZM_JWT_SECRET / ZM_DEMO_PASSWORD 未设置时自动生成到数据目录（0600），且不出现在 /api/health。"""
    d = Path(os.environ["ZM_DATA_DIR"])
    health = anon.get("/api/health")
    assert "auth" in health.json() and "required" in health.json()["auth"], health.text[:200]
    for f, env in (("jwt_secret", "ZM_JWT_SECRET"), ("demo_password.txt", "ZM_DEMO_PASSWORD")):
        if os.getenv(env):
            continue
        p = d / f
        assert p.is_file(), f"缺少自动生成的 {p}"
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, oct(p.stat().st_mode)
        val = p.read_text().strip()
        assert len(val) >= 16
        assert val not in health.text


# ======================= 当前用户 / 匿名（两种模式） =======================
def test_me_anonymous_default_mode_acts_as_demo(anon, required):
    if required:
        pytest.skip("ZM_AUTH_REQUIRED=1：见 test_me_anonymous_required_mode")
    r = anon.get("/api/auth/me")
    assert r.status_code == 401 and code(r) == "unauthorized", r.text[:200]
    j = r.json()
    assert j["auth_required"] is False and j["acting_as"]["id"] == "u_demo"
    assert anon.get("/api/health").json()["auth"]["required"] is False


def test_me_anonymous_required_mode(anon, required):
    if not required:
        pytest.skip("默认 ZM_AUTH_REQUIRED=0：请用 ZM_AUTH_REQUIRED=1 再跑一遍（scripts/qa.sh api 会自动两种模式各跑一遍）")
    r = anon.get("/api/auth/me")
    assert r.status_code == 401 and code(r) == "unauthorized", r.text[:200]
    j = r.json()
    assert j["auth_required"] is True and j.get("acting_as") is None
    assert anon.get("/api/health").json()["auth"]["required"] is True


ANON_PROTECTED = [
    ("GET", "/api/worlds", None), ("POST", "/api/worlds", GEN), ("POST", "/api/worlds/generate", GEN),
    ("POST", "/api/worlds/import", {"format": "zhimeng-save"}), ("POST", "/api/education/generate", EDU),
    ("GET", "/api/users/me/stats", None), ("GET", "/api/users/me/preferences", None),
    ("GET", "/api/users/me/learning", None), ("POST", "/api/reports", {"content": "x", "reason": "other"}),
    ("GET", "/api/assets/a_doesnotexist", None),
]


@pytest.mark.parametrize("method, path, body", ANON_PROTECTED, ids=[f"{m} {p}" for m, p, _ in ANON_PROTECTED])
def test_anonymous_rejected_when_required(anon, required, method, path, body):
    if not required:
        pytest.skip("默认 ZM_AUTH_REQUIRED=0 匿名按 u_demo 放行（见 test_anonymous_is_demo_by_default）")
    r = anon.get(path) if method == "GET" else anon.post(path, body)
    assert r.status_code == 401 and code(r) == "unauthorized", f"{method} {path}: {r.status_code} {r.text[:200]}"


def test_anonymous_is_demo_by_default(anon, alice, required):
    if required:
        pytest.skip("ZM_AUTH_REQUIRED=1：匿名一律 401（见 test_anonymous_rejected_when_required）")
    r = anon.post("/api/worlds", GEN)
    assert r.status_code == 200, r.text[:200]
    w = r.json()
    assert w.get("owner_id") == "u_demo", f"匿名创建的世界应归 u_demo: {w.get('owner_id')}"
    assert w["id"] in [x["id"] for x in anon.get("/api/worlds").json()]
    assert anon.get("/api/users/me/stats").status_code == 200
    assert anon.get("/api/users/me/preferences").status_code == 200
    # demo 的世界对登录用户同样不可见
    assert_404(alice.get(f"/api/worlds/{w['id']}"), "alice 读 demo 世界")
    assert w["id"] not in [x["id"] for x in alice.get("/api/worlds").json()]


@pytest.mark.parametrize("method, path, body", [
    ("PATCH", "/api/users/me", {"nickname": "x"}), ("PATCH", "/api/auth/me", {"nickname": "x"}),
    ("PUT", "/api/users/me/password", {"current_password": "a", "new_password": "Newpass-2026x"}),
])
def test_profile_writes_always_need_real_login(anon, method, path, body):
    r = anon.patch(path, body) if method == "PATCH" else anon.put(path, body)
    assert r.status_code == 401 and code(r) == "unauthorized", f"{method} {path}: {r.status_code} {r.text[:200]}"


@pytest.mark.parametrize("cookie", ["zm_access=forged.jwt.value",
                                    "zm_access=eyJhbGciOiJub25lIn0.eyJzdWIiOiJ1X2RlbW8iLCJ0eXAiOiJhY2Nlc3MifQ."])
def test_forged_access_cookie_401(client, cookie):
    f = UserApi(client, {"Cookie": cookie})
    for path in ("/api/auth/me", "/api/worlds"):
        r = f.get(path)
        assert r.status_code == 401 and code(r) == "token_expired", \
            f"伪造 zm_access {path} → {r.status_code} {code(r)}（不得降级为 demo）"


def test_unknown_cookie_name_not_a_session(client):
    r = UserApi(client, {"Cookie": "zm_session=anything; session=x"}).get("/api/auth/me")
    assert r.status_code == 401 and code(r) == "unauthorized", r.text[:200]


def test_access_signed_with_other_secret_rejected(client, alice):
    jwt = pytest.importorskip("jwt")
    import time
    tok = jwt.encode({"sub": alice.user.get("id", "u_x"), "typ": "access", "ver": 0, "iat": int(time.time()),
                      "exp": int(time.time()) + 600}, "not-the-server-secret-" + "x" * 40, algorithm="HS256")
    assert UserApi(client, {"Cookie": f"zm_access={tok}"}).get("/api/worlds").status_code == 401


def test_public_endpoints_open(anon):
    for p in ("/api/health", "/api/safety/policy"):
        assert anon.get(p).status_code == 200, p
    assert anon.post("/api/safety/check", {"text": "你好"}).status_code == 200
    assert anon.post("/api/auth/logout").status_code == 204, "未登录登出幂等 204"


def test_debug_status_requires_login(anon, alice):
    r = anon.get("/api/debug/status")
    assert r.status_code == 401 and code(r) == "unauthorized", r.text[:200]
    ok = alice.get("/api/debug/status")
    assert ok.status_code == 200 and "auth_required" in ok.json()
    assert "secret" not in ok.text.lower() and "dashscope_api_key" not in ok.text.lower()


def test_origin_check_on_writes(alice):
    r = alice.post("/api/worlds", GEN, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and code(r) == "forbidden", f"跨站 Origin 写请求应 403 forbidden: {r.status_code}"
    ok = alice.get("/api/worlds", headers={"Origin": "http://localhost:3000"})
    assert ok.status_code == 200


# ======================= 权限隔离 =======================
def test_world_owner_fields_and_list_scoped(alice, bob, alice_world):
    assert alice_world["world"].get("owner_id") == alice.user["id"]
    assert alice_world["world"].get("origin") == "generated"
    a = alice.get("/api/worlds").json()
    assert alice_world["id"] in [w["id"] for w in a]
    assert all(w.get("owner_id") == alice.user["id"] for w in a)
    assert alice_world["id"] not in [w["id"] for w in bob.get("/api/worlds").json()]


READ_PATHS = [
    "/api/worlds/{wid}", "/api/worlds/{wid}/turns", "/api/worlds/{wid}/options", "/api/worlds/{wid}/events",
    "/api/worlds/{wid}/memory", "/api/worlds/{wid}/summaries", "/api/worlds/{wid}/assets", "/api/worlds/{wid}/ui",
    "/api/worlds/{wid}/god/npcs", "/api/worlds/{wid}/export", "/api/worlds/{wid}/poster",
    "/api/worlds/{wid}/education/cards", "/api/worlds/{wid}/education/summary", "/api/reports?world_id={wid}",
]


@pytest.mark.parametrize("tpl", READ_PATHS)
def test_other_user_cannot_read(alice, bob, alice_world, tpl):
    path = tpl.format(wid=alice_world["id"])
    assert alice.get(path).status_code == 200, f"owner should read {path}"
    r = bob.get(path)
    assert_404(r, f"bob GET {path}")
    assert alice_world["title"] not in r.text


WRITE_CALLS = [
    ("POST", "/api/worlds/{wid}/turns", {"action": "我偷看别人的世界", "client_turn_id": "x-" + uuid.uuid4().hex}),
    ("POST", "/api/worlds/{wid}/turns/retry", {}),
    ("POST", "/api/worlds/{wid}/regenerate", {}),
    ("POST", "/api/worlds/{wid}/confirm", None),
    ("PATCH", "/api/worlds/{wid}/settings", {"minor_mode": True}),
    ("POST", "/api/worlds/{wid}/god/inject", {"content": "码头突发大火", "impact": "high"}),
    ("POST", "/api/worlds/{wid}/god/tick", None),
    ("POST", "/api/worlds/{wid}/memory/query", {"question": "线人叫什么？"}),
    ("POST", "/api/worlds/{wid}/events/seen", {"ids": []}),
    ("POST", "/api/worlds/{wid}/ui/stream", {}),
    ("POST", "/api/worlds/{wid}/assets/illustration", {"prompt": "测试"}),
    ("POST", "/api/worlds/{wid}/assets/tts", {"text": "测试"}),
    ("POST", "/api/reports", {"world_id": "{wid}", "content": "x", "reason": "other"}),
    ("DELETE", "/api/worlds/{wid}", None),
]


@pytest.mark.parametrize("method, tpl, body", WRITE_CALLS, ids=[f"{m} {p}" for m, p, _ in WRITE_CALLS])
def test_other_user_cannot_write(alice, bob, alice_world, method, tpl, body):
    """含 SSE 接口：鉴权在建流之前，必须直接返回 HTTP 404 JSON，而不是 200 再在流里报错。"""
    wid = alice_world["id"]
    path = tpl.format(wid=wid)
    if isinstance(body, dict):
        body = {k: (v.format(wid=wid) if isinstance(v, str) else v) for k, v in body.items()}
    before = alice.get(f"/api/worlds/{wid}").json()
    turns_before = len(alice.get(f"/api/worlds/{wid}/turns").json())
    if method == "PATCH":
        r = bob.patch(path, body)
    elif method == "DELETE":
        r = bob.delete(path)
    else:
        r = bob.post(path, body)
    assert "text/event-stream" not in r.headers.get("content-type", ""), "越权的 SSE 请求不应建立流"
    assert_404(r, f"bob {method} {path}")
    after = alice.get(f"/api/worlds/{wid}")
    assert after.status_code == 200, "alice 的世界被他人删除"
    assert after.json().get("minor_mode") == before.get("minor_mode")
    assert len(alice.get(f"/api/worlds/{wid}/turns").json()) == turns_before


def test_other_user_cannot_access_asset_by_id(alice, bob, alice_world):
    aid = alice_world["asset_id"]
    assert alice.get(f"/api/assets/{aid}").status_code == 200
    assert_404(bob.get(f"/api/assets/{aid}"), "bob GET asset")
    assert_404(bob.post(f"/api/assets/{aid}/regenerate"), "bob regenerate asset")


def test_import_creates_copy_owned_by_importer(alice, bob, alice_world):
    save = alice.get(f"/api/worlds/{alice_world['id']}/export").json()
    save["world"]["owner_id"] = alice.user["id"]  # 存档里的 owner_id 必须被忽略
    r = bob.post("/api/worlds/import", save)
    assert r.status_code == 200, r.text[:200]
    w = r.json()
    assert w["id"] != alice_world["id"]
    assert w.get("owner_id") == bob.user["id"] and w.get("origin") == "imported", w.get("owner_id")
    assert w["id"] in [x["id"] for x in bob.get("/api/worlds").json()]
    assert w["id"] not in [x["id"] for x in alice.get("/api/worlds").json()]
    assert_404(alice.get(f"/api/worlds/{w['id']}"), "alice 读 bob 导入的世界")


def test_streaming_generate_owned_by_creator(alice, bob):
    ev = bob.sse("/api/worlds/generate", GEN)
    w = first(ev, "world")
    assert w and first(ev, "done")
    assert w["id"] in [x["id"] for x in bob.get("/api/worlds").json()]
    assert_404(alice.get(f"/api/worlds/{w['id']}"), "alice 读 bob 的世界")


def test_education_world_owned_by_creator(alice, bob):
    ev = bob.sse("/api/education/generate", EDU)
    w = first(ev, "world")
    assert w, [n for n, _ in ev]
    assert_404(alice.get(f"/api/worlds/{w['id']}/education/cards"), "alice 读 bob 的知识卡")


def test_owner_can_delete_own_world(alice):
    w = alice.post("/api/worlds", GEN).json()
    assert alice.delete(f"/api/worlds/{w['id']}").status_code == 200
    assert alice.get(f"/api/worlds/{w['id']}").status_code == 404


# ======================= 个人中心 =======================
def test_profile_me(alice):
    j = alice.get("/api/auth/me").json()
    assert j["authenticated"] is True
    u = j["user"]
    assert u["username"] == alice.username
    assert {"id", "username", "email", "nickname", "avatar_url", "bio", "preferences", "is_demo", "created_at"} <= set(u)
    assert not any("password" in k.lower() or "hash" in k.lower() for k in u)


@pytest.mark.parametrize("path", ["/api/users/me", "/api/auth/me"])
def test_profile_update_nickname(alice, path):
    nick = "爱丽丝" + path[-2:]
    r = alice.patch(path, {"nickname": nick, "bio": "喜欢民国悬疑"})
    assert r.status_code == 200, f"PATCH {path}: {r.status_code} {r.text[:200]}"
    assert r.json()["user"]["nickname"] == nick
    assert alice.get("/api/auth/me").json()["user"]["nickname"] == nick
    for bad in ("", "   ", "a\x07b", "长" * 21):
        rb = alice.patch(path, {"nickname": bad})
        assert rb.status_code == 422 and code(rb) == "validation_error", f"nickname={bad!r}: {rb.status_code}"


def test_profile_stats_scoped(alice, bob, alice_world):
    r = alice.get("/api/users/me/stats")
    assert r.status_code == 200, r.text[:200]
    a = r.json()
    assert a["worlds"]["total"] >= 1 and a["play"]["turns"] >= 1, a
    assert {"worlds", "summaries", "latest"} <= set(a["learning"]), a["learning"]
    assert alice_world["id"] in [w["id"] for w in a["recent_worlds"]]
    b = bob.get("/api/users/me/stats").json()
    assert alice_world["id"] not in [w["id"] for w in b["recent_worlds"]]
    assert b["worlds"]["total"] == len(bob.get("/api/worlds").json())


def test_preferences_minor_mode_is_floor(client):
    u = _user(client, "pref")
    assert u.patch("/api/users/me/preferences", {"minor_mode": True}).json()["preferences"]["minor_mode"] is True
    w = u.post("/api/worlds", {**GEN, "minor_mode": False, "rating": "mature"}).json()
    assert w["minor_mode"] is True, "偏好开启未成年人模式时，请求只能更严格"
    assert w["rating"] in ("all", "teen")
    st = u.patch(f"/api/worlds/{w['id']}/settings", {"minor_mode": False})
    assert st.status_code == 200 and st.json()["minor_mode"] is True, "偏好开启时 settings 的 minor_mode:false 应被忽略"
    assert "minor_mode" in st.headers.get("x-zm-clamped", ""), st.headers.get("x-zm-clamped")
    off = u.patch("/api/users/me/preferences", {"minor_mode": False})
    assert off.status_code == 401 and code(off) == "wrong_password", "关闭未成年人模式需当前密码"
    put_off = u.put("/api/users/me/preferences", {"tts_enabled": False})  # PUT 漏传 minor_mode = 回到默认 false = 关闭
    assert put_off.status_code == 401 and code(put_off) == "wrong_password", put_off.text[:200]
    ok = u.patch("/api/users/me/preferences", {"minor_mode": False, "current_password": AUTH_PASSWORD})
    assert ok.status_code == 200 and ok.json()["preferences"]["minor_mode"] is False
    full = u.put("/api/users/me/preferences", {"preferences": {"minor_mode": False, "tts_enabled": False}})
    assert full.status_code == 200
    p = full.json()["preferences"]
    assert p["tts_enabled"] is False and p["autoplay_audio"] is False and p["rating"] == "teen", "PUT 缺省字段回默认值"


def test_learning_records_scoped(alice, bob):
    ev = alice.sse("/api/education/generate", EDU)
    w = first(ev, "world")
    assert w
    a = alice.get("/api/users/me/learning?limit=5")
    assert a.status_code == 200, a.text[:200]
    j = a.json()
    assert {"items", "total", "limit", "offset"} <= set(j) and j["limit"] == 5
    assert w["id"] in [x["world_id"] for x in j["items"]]
    assert w["id"] not in [x["world_id"] for x in bob.get("/api/users/me/learning").json()["items"]]
    assert alice.get("/api/users/me/learning?limit=0").status_code == 422


# ======================= 改密码 =======================
@pytest.mark.parametrize("method", ["PUT", "POST"])
def test_change_password(client, method):
    _, name = register_user(client, unique_name("chpw"))
    s1 = UserApi(client, credentials(login_user(client, name)))  # 本设备
    s2 = UserApi(client, credentials(login_user(client, name)))  # 另一台设备
    call = s1.put if method == "PUT" else s1.post
    bad = call("/api/users/me/password", {"current_password": "Wrong-pass-999", "new_password": "Newpass-2026x"})
    assert bad.status_code == 401 and code(bad) == "wrong_password", bad.text[:200]
    same = call("/api/users/me/password", {"current_password": AUTH_PASSWORD, "new_password": AUTH_PASSWORD})
    assert same.status_code == 400 and code(same) == "same_password", same.text[:200]
    ok = call("/api/users/me/password", {"current_password": AUTH_PASSWORD, "new_password": "Newpass-2026x"})
    assert ok.status_code == 204, ok.text[:200]
    r2 = s2.get("/api/auth/me")
    assert r2.status_code == 401 and code(r2) == "token_expired", "改密码后其他设备的 access 应立即失效（token_version+1）"
    if credentials(ok):  # 本设备重新签发 cookie
        assert UserApi(client, credentials(ok)).get("/api/auth/me").json()["authenticated"] is True
    assert login_user(client, name).status_code == 401, "旧密码仍可登录"
    assert login_user(client, name, "Newpass-2026x").status_code == 200


# ======================= refresh / 登出 =======================
def test_refresh_rotates_and_detects_replay(client):
    r, _ = register_user(client)
    old = credentials(r)
    r1 = UserApi(client, old).post("/api/auth/refresh")
    assert r1.status_code == 200 and r1.json()["user"], r1.text[:200]
    new = cookie_values(r1)
    assert new.get("zm_refresh") and new["zm_refresh"] != cookie_values(r)["zm_refresh"], "refresh 应轮换"
    replay = UserApi(client, old).post("/api/auth/refresh")
    assert replay.status_code == 401 and code(replay) == "refresh_invalid", "重放旧 refresh 应 401"
    again = UserApi(client, credentials(r1)).post("/api/auth/refresh")
    assert again.status_code == 401, "检测到重放后整串 family 应吊销"


def test_logout_clears_and_revokes(client):
    _, name = register_user(client, unique_name("logout"))
    r = login_user(client, name)
    cred = credentials(r)
    u = UserApi(client, cred)
    assert u.get("/api/auth/me").json()["authenticated"] is True
    out = u.post("/api/auth/logout")
    assert out.status_code == 204, out.text[:200]
    cleared = " ".join(out.headers.get_list("set-cookie")).lower() if hasattr(out.headers, "get_list") else \
        out.headers.get("set-cookie", "").lower()
    assert "zm_access=" in cleared and "zm_refresh=" in cleared and ("max-age=0" in cleared or "expires=" in cleared), \
        f"登出应清除两个 cookie: {cleared[:200]}"
    # 服务端吊销：同一会话被复制的 access / refresh 都失效
    assert UserApi(client, cred).get("/api/auth/me").status_code == 401, "登出后同一会话的 access 仍有效"
    assert UserApi(client, cred).get("/api/worlds").status_code == 401, "登出后复制的 access 仍可访问数据"
    rf = UserApi(client, cred).post("/api/auth/refresh")
    assert rf.status_code == 401 and code(rf) == "refresh_invalid", "登出后 refresh 应失效"
    assert login_user(client, name).status_code == 200


def test_logout_only_this_session(client):
    _, name = register_user(client, unique_name("multi"))
    s1 = UserApi(client, credentials(login_user(client, name)))
    c2 = credentials(login_user(client, name))
    assert s1.post("/api/auth/logout").status_code == 204
    assert UserApi(client, c2).get("/api/auth/me").status_code == 200, "登出一个设备不应影响其他设备"
    assert UserApi(client, c2).post("/api/auth/refresh").status_code == 200


# ======================= 头像 =======================
def _png(w=8, h=8) -> bytes:
    import struct
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\x80\x00" * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_avatar_upload_rules(client, anon):
    u = _user(client, "avatar")
    up = lambda name, data, ct: u.c.post("/api/users/me/avatar", files={"file": (name, data, ct)},  # noqa: E731
                                         headers=u.h)
    u.c.cookies.clear()
    ok = up("a.png", _png(300, 200), "image/png")
    assert ok.status_code == 200, ok.text[:200]
    url = ok.json()["avatar_url"]
    assert url.startswith("/api/static/avatars/") and url.split("?")[0].endswith(".webp")
    img = anon.get(url)
    assert img.status_code == 200 and img.content[:4] == b"RIFF" and img.content[8:12] == b"WEBP", "应转码为 webp"
    u.c.cookies.clear()
    assert up("a.gif", b"GIF89a" + b"\x00" * 64, "image/gif").status_code == 415
    u.c.cookies.clear()
    assert up("fake.png", b"%PDF-1.4 not an image", "image/png").status_code == 415, "按文件头判断真实类型"
    u.c.cookies.clear()
    broken = up("b.png", _png()[:40], "image/png")
    assert broken.status_code == 400 and code(broken) == "invalid_image", broken.text[:200]
    u.c.cookies.clear()
    big = up("big.png", _png() + b"\x00" * (2 * 1024 * 1024 + 10), "image/png")
    assert big.status_code == 413 and code(big) == "file_too_large", big.text[:200]
    anon.c.cookies.clear()
    assert anon.c.post("/api/users/me/avatar", files={"file": ("a.png", _png(), "image/png")}).status_code == 401
    d = u.delete("/api/users/me/avatar")
    assert d.status_code == 200 and d.json()["avatar_url"] is None


# ======================= 演示账号（旧数据） =======================
@pytest.mark.skipif(bool(LIVE), reason="读取进程内临时数据目录中的 demo_password.txt，仅进程内模式")
def test_demo_account_login_sees_demo_worlds(client):
    """README「登录演示账号看旧数据」：demo + demo_password.txt（或 ZM_DEMO_PASSWORD）可登录，看到归 u_demo 的世界。"""
    pw = os.getenv("ZM_DEMO_PASSWORD") or (Path(os.environ["ZM_DATA_DIR"]) / "demo_password.txt").read_text().strip()
    r = login_user(client, "demo", pw)
    assert r.status_code == 200, r.text[:200]
    u = r.json()["user"]
    assert u["id"] == "u_demo" and u["is_demo"] is True
    demo = UserApi(client, credentials(r))
    for w in demo.get("/api/worlds").json():
        assert w.get("owner_id") == "u_demo"
    ro = demo.patch("/api/users/me", {"nickname": "改名"})
    assert ro.status_code == 403 and code(ro) == "demo_readonly", ro.text[:200]


# ======================= AUTH-QA-3：伪造 XFF / 代理不传 XFF 的兜底（契约 §5、§13） =======================
# 进程内客户端对端为 127.0.0.1（默认可信代理）。阈值用环境变量临时调小，用例结束恢复（get_settings 缓存同步清理），
# 每个用例用独立账号与 198.18.0.0/15 来源 IP，互不影响。
@pytest.fixture
def tune(monkeypatch):
    if LIVE:
        pytest.skip("需在进程内调整阈值（环境变量 + get_settings.cache_clear）")
    from app.config import get_settings

    def _set(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        get_settings.cache_clear()
    yield _set
    monkeypatch.undo()
    get_settings.cache_clear()


def _assert_locked(r, what=""):
    assert r.status_code == 429 and code(r) == "rate_limited", f"{what}: {r.status_code} {r.text[:200]}"
    ra = r.headers.get("retry-after")
    assert ra and ra.isdigit() and int(ra) > 0, f"{what}: Retry-After={ra}"
    assert int(r.json().get("retry_after", 0)) > 0, f"{what}: {r.text[:200]}"


def test_account_lock_default_10_with_rotating_forged_xff(client):
    """默认 ZM_LOGIN_ACCOUNT_MAX_FAILS=10：每次换一个伪造来源 IP 也绕不过按账号上限；锁定期间正确密码也 429。"""
    _, name = register_user(client, unique_name("acct"))
    codes = [login_user(client, name, f"Guess{i}abc9", ip=unique_ip()).status_code for i in range(10)]
    assert codes == [401] * 10, codes
    _assert_locked(login_user(client, name, ip=unique_ip()), "第 11 次（正确密码、新 IP）")
    other, _ = register_user(client, unique_name("acctok"))
    assert other.status_code == 201
    assert login_user(client, other.json()["user"]["username"], ip=unique_ip()).status_code == 200, "别的账号不受影响"


def test_account_lock_success_does_not_reset(client, tune):
    tune(ZM_LOGIN_ACCOUNT_MAX_FAILS=4)
    _, name = register_user(client, unique_name("noreset"))
    for _ in range(3):
        assert login_user(client, name, "Wrong-pass-999", ip=unique_ip()).status_code == 401
    assert login_user(client, name, ip=unique_ip()).status_code == 200
    assert login_user(client, name, "Wrong-pass-999", ip=unique_ip()).status_code == 401
    _assert_locked(login_user(client, name, ip=unique_ip()), "登录成功不清零：第 4 次失败后应锁")


def test_account_lock_merges_username_and_email(client, tune):
    tune(ZM_LOGIN_ACCOUNT_MAX_FAILS=4)
    email = f"m{uuid.uuid4().hex[:6]}@example.com"
    _, name = register_user(client, unique_name("merge"), email=email)
    for login in (name, name.upper(), email, email.upper()):
        assert login_user(client, login, "Wrong-pass-999", ip=unique_ip()).status_code == 401
    _assert_locked(login_user(client, name, ip=unique_ip()), "用户名登录")
    _assert_locked(login_user(client, email, ip=unique_ip()), "邮箱登录")


def test_unknown_username_same_response_and_counted(client, tune):
    tune(ZM_LOGIN_ACCOUNT_MAX_FAILS=3)
    _, real = register_user(client, unique_name("real"))
    ghost = unique_name("ghost")
    pairs = [(login_user(client, real, "Wrong-pass-999", ip=unique_ip()),
              login_user(client, ghost, "Wrong-pass-999", ip=unique_ip())) for _ in range(3)]
    for a, b in pairs:
        assert (a.status_code, code(a), a.json().get("detail")) == (b.status_code, code(b), b.json().get("detail"))
    la, lb = login_user(client, real, ip=unique_ip()), login_user(client, ghost, ip=unique_ip())
    _assert_locked(la, "存在的账号")
    _assert_locked(lb, "不存在的账号（也计数）")
    assert set(la.json()) == set(lb.json()) and la.headers.get("retry-after") and lb.headers.get("retry-after")
    assert abs(int(la.json()["retry_after"]) - int(lb.json()["retry_after"])) <= 5, "锁定提示不应暴露账号是否存在"


def test_proxy_hops_default_rightmost_only(client):
    """ZM_PROXY_HOPS=1：只取 XFF 最右项；左边（客户端可伪造）的条目怎么变都不影响按 IP+账号计数。"""
    _, name = register_user(client, unique_name("hop1"))
    ip = unique_ip()
    for i in range(5):
        r = client.post("/api/auth/login", json={"login": name, "password": "Wrong-pass-999"},
                        headers={"X-Forwarded-For": f"203.0.113.{i + 1}, {ip}"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"login": name, "password": AUTH_PASSWORD},
                    headers={"X-Forwarded-For": f"203.0.113.99, {ip}"})
    _assert_locked(r, "最右项相同 → 同一 IP，第 6 次应被 IP+账号规则锁")
    ok = client.post("/api/auth/login", json={"login": name, "password": AUTH_PASSWORD},
                     headers={"X-Forwarded-For": f"{ip}, {unique_ip()}"})
    assert ok.status_code == 200, "最右项不同 = 不同客户端（左边写同一 IP 也不算）"


def test_proxy_hops_2(client, tune):
    tune(ZM_PROXY_HOPS=2)
    _, name = register_user(client, unique_name("hop2"), ip=unique_ip())
    ip = unique_ip()
    for i in range(5):  # 客户端真实 IP 在从右数第 2 项，最右是内层代理（每次变化也不影响）
        assert client.post("/api/auth/login", json={"login": name, "password": "Wrong-pass-999"},
                           headers={"X-Forwarded-For": f"203.0.113.7, {ip}, 10.9.0.{i + 1}"}).status_code == 401
    r = client.post("/api/auth/login", json={"login": name, "password": AUTH_PASSWORD},
                    headers={"X-Forwarded-For": f"{ip}, 10.9.0.50"})
    _assert_locked(r, "HOPS=2 取从右数第 2 项")
    # 条目少于 hops → IP 未知：按 IP 的规则不生效（同一单项 XFF 连续失败 6 次也不被 IP+账号锁）
    _, n2 = register_user(client, unique_name("hop2u"), ip=unique_ip())
    single = unique_ip()
    codes = [client.post("/api/auth/login", json={"login": n2, "password": "Wrong-pass-999"},
                         headers={"X-Forwarded-For": single}).status_code for _ in range(6)]
    assert codes == [401] * 6, codes
    assert client.post("/api/auth/login", json={"login": n2, "password": AUTH_PASSWORD},
                       headers={"X-Forwarded-For": single}).status_code == 200


def _login_no_xff(client, login, pw=AUTH_PASSWORD):
    client.cookies.clear()
    return client.post("/api/auth/login", json={"login": login, "password": pw})


def test_unknown_ip_does_not_lock_everyone(client, tune):
    """代理没传 XFF（可信对端、无 XFF/X-Real-IP）= IP 未知：一个账号被锁、全站累计 20+ 次失败，都不影响其他账号。"""
    tune(ZM_LOGIN_ACCOUNT_MAX_FAILS=4)
    users = [register_user(client, unique_name("unk"))[1] for _ in range(7)]
    victim, bystander = users[0], users[-1]
    for _ in range(4):
        assert _login_no_xff(client, victim, "Wrong-pass-999").status_code == 401
    _assert_locked(_login_no_xff(client, victim), "被按账号锁定")
    for u in users[1:6]:  # 5 个账号各失败 3 次 + 上面 4 次 = 19；再补 2 次 → 全站无 XFF 累计 21 次失败
        for _ in range(3):
            assert _login_no_xff(client, u, "Wrong-pass-999").status_code == 401
    for _ in range(2):
        assert _login_no_xff(client, users[1], "Wrong-pass-999").status_code in (401, 429)
    assert _login_no_xff(client, bystander).status_code == 200, "IP 未知时不应因他人失败而全站误锁"


def test_unknown_ip_register_not_per_ip_limited(client):
    client.cookies.clear()
    codes = [client.post("/api/auth/register", json={"username": unique_name("noxff"), "password": AUTH_PASSWORD,
                                                      "nickname": "无XFF"}).status_code for _ in range(11)]
    assert codes == [201] * 11, f"IP 未知时不应套用每 IP 10 次/小时：{codes}"


def test_global_register_cap(client, tune):
    tune(ZM_REGISTER_GLOBAL_PER_HOUR=1)  # 本进程本小时早已注册多次 → 立刻触发全站上限
    r, _ = register_user(client, unique_name("cap"))
    _assert_locked(r, "全站注册上限（带 XFF）")
    client.cookies.clear()
    r2 = client.post("/api/auth/register", json={"username": unique_name("cap2"), "password": AUTH_PASSWORD, "nickname": "x"})
    _assert_locked(r2, "全站注册上限（IP 未知也生效）")
