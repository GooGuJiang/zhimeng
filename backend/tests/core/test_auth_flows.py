"""v1.4 用户系统：注册 / 登录 / 限流 / 刷新轮换 / 重放吊销 / 登出 / 改密码 / 资料 / 头像 / 可信代理。"""
from __future__ import annotations

import pytest

from auth_helpers import PW, new_client, png_bytes, register, setenv, uname, user_client


def code(r):
    return r.json().get("code")


def test_register_login_me_cookie_flags(client):
    r, name = register(client, email="Alice@Example.com", nickname="林小雨")
    assert r.status_code == 201
    u = r.json()["user"]
    assert u["username"] == name and u["email"] == "alice@example.com" and u["nickname"] == "林小雨"
    assert not any("password" in k or "hash" in k for k in u)
    sc = r.headers.get_list("set-cookie")
    acc = next(x for x in sc if x.startswith("zm_access="))
    ref = next(x for x in sc if x.startswith("zm_refresh="))
    assert "HttpOnly" in acc and "Path=/api" in acc and "samesite=lax" in acc.lower() and "Secure" not in acc
    assert "Path=/api/auth" in ref and "HttpOnly" in ref
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["authenticated"] is True and me.json()["user"]["id"] == u["id"]
    client.cookies.clear()
    for login in (name.upper(), "ALICE@example.com"):
        r = client.post("/api/auth/login", json={"login": login, "password": PW})
        assert r.status_code == 200 and r.json()["user"]["id"] == u["id"]


def test_register_validation(client):
    assert code(register(client, "1abc")[0]) == "validation_error"           # 必须字母开头（AUTH-QA-2）
    assert code(register(client, "_abc")[0]) == "validation_error"
    assert code(register(client, "ab")[0]) == "validation_error"
    assert register(client, "a" * 21)[0].json()["field"] == "username"
    assert code(register(client, "Demo")[0]) == "username_reserved"
    assert code(register(client, password="short1")[0]) == "weak_password"
    assert code(register(client, password="abcdefghij")[0]) == "weak_password"
    assert code(register(client, password="a1" * 33)[0]) == "weak_password"  # 上限 64
    assert register(client, password="a1" * 32)[0].status_code == 201
    assert code(register(client, password="password123")[0]) == "weak_password"
    assert code(register(client, email="not-an-email")[0]) == "validation_error"
    r, name = register(client)
    assert code(register(client, name.upper())[0]) == "username_taken"
    register(client, email="dup@x.com")
    assert code(register(client, email="DUP@x.com")[0]) == "email_taken"
    assert code(register(client, nickname="a\x07b")[0]) == "validation_error"


def test_me_anonymous_401_with_demo_hint(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and code(r) == "unauthorized"
    assert r.json()["auth_required"] is False and r.json()["acting_as"]["id"] == "u_demo"
    assert client.get("/api/health").json()["auth"] == {"required": False}


@pytest.mark.parametrize("cookie", ["zm_access=garbage", "zm_session=forged-session",
                                    "zm_access=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1X2RlbW8iLCJ0eXAiOiJhY2Nlc3MifQ.x"])
def test_forged_cookies_never_authenticate(client, cookie):
    r = client.get("/api/auth/me", headers={"Cookie": cookie})
    assert r.status_code == 401
    assert code(r) == ("token_expired" if cookie.startswith("zm_access") else "unauthorized")
    if cookie.startswith("zm_access"):  # 带了坏 access 时受保护接口也不会悄悄当成 demo
        assert code(client.get("/api/worlds", headers={"Cookie": cookie})) == "token_expired"


def test_forged_jwt_with_other_secret_rejected(client):
    import jwt as pyjwt
    tok = pyjwt.encode({"sub": "u_demo", "typ": "access", "ver": 1, "fam": "x", "exp": 9999999999}, "x" * 64,
                       algorithm="HS256")
    assert code(client.get("/api/auth/me", headers={"Cookie": f"zm_access={tok}"})) == "token_expired"


def test_login_rate_limit_and_lock(client):
    r, name = register(client)
    client.cookies.clear()
    for _ in range(5):
        assert code(client.post("/api/auth/login", json={"login": name, "password": "Wrong#123x"})) == "invalid_credentials"
    r = client.post("/api/auth/login", json={"login": name, "password": PW})  # 锁定期内正确密码也 429
    assert r.status_code == 429 and code(r) == "rate_limited"
    assert 0 < r.json()["retry_after"] <= 300 and int(r.headers["Retry-After"]) == r.json()["retry_after"]
    # 不存在的用户同样计数、同样文案
    r = client.post("/api/auth/login", json={"login": "nobody_here", "password": "Wrong#123x"})
    assert code(r) == "invalid_credentials" and r.json()["detail"] == "用户名或密码错误"


def test_login_success_clears_counter(client):
    r, name = register(client)
    client.cookies.clear()
    for _ in range(4):
        client.post("/api/auth/login", json={"login": name, "password": "Wrong#123x"})
    assert client.post("/api/auth/login", json={"login": name, "password": PW}).status_code == 200
    for _ in range(4):
        client.post("/api/auth/login", json={"login": name, "password": "Wrong#123x"})
    assert client.post("/api/auth/login", json={"login": name, "password": PW}).status_code == 200


def test_register_rate_limit_per_ip(core_env, monkeypatch):
    setenv(monkeypatch, ZM_REGISTER_PER_HOUR=3)
    with new_client("203.0.113.7") as c:
        for _ in range(3):
            assert register(c)[0].status_code == 201
        r = register(c)[0]
        assert r.status_code == 429 and code(r) == "rate_limited" and r.json()["retry_after"] > 0


def test_refresh_rotation_and_reuse_revokes_family(client):
    register(client)
    old_ref = client.cookies.get("zm_refresh")
    r = client.post("/api/auth/refresh")
    assert r.status_code == 200 and r.json()["user"]
    new_ref = client.cookies.get("zm_refresh")
    assert new_ref and new_ref != old_ref
    assert client.get("/api/auth/me").status_code == 200
    # 重放已作废的 refresh → 401 且整串吊销（新 refresh 与该会话的 access 都失效）
    acc = client.cookies.get("zm_access")
    client.cookies.clear()
    bad = client.post("/api/auth/refresh", headers={"Cookie": f"zm_refresh={old_ref}"})
    assert bad.status_code == 401 and code(bad) == "refresh_invalid"
    assert code(client.post("/api/auth/refresh", headers={"Cookie": f"zm_refresh={new_ref}"})) == "refresh_invalid"
    assert code(client.get("/api/auth/me", headers={"Cookie": f"zm_access={acc}"})) == "token_expired"


def test_logout_only_kills_this_session(core_env):
    with new_client() as a:
        r, name = register(a)
        with new_client() as b:
            assert b.post("/api/auth/login", json={"login": name, "password": PW}).status_code == 200
            acc, ref = a.cookies.get("zm_access"), a.cookies.get("zm_refresh")
            out = a.post("/api/auth/logout")
            assert out.status_code == 204 and out.content == b""
            assert a.get("/api/auth/me", headers={"Cookie": f"zm_access={acc}"}).status_code == 401
            assert code(a.post("/api/auth/refresh", headers={"Cookie": f"zm_refresh={ref}"})) == "refresh_invalid"
            assert b.get("/api/auth/me").status_code == 200
    with new_client() as anon:
        assert anon.post("/api/auth/logout").status_code == 204


@pytest.mark.parametrize("method", ["post", "put"])
def test_change_password(core_env, method):
    with new_client() as a, new_client() as other:
        r, name = register(a)
        other.post("/api/auth/login", json={"login": name, "password": PW})
        fn = getattr(a, method)
        bad = fn("/api/users/me/password", json={"current_password": "Nope#1234", "new_password": "Brand#New99"})
        assert bad.status_code == 401 and code(bad) == "wrong_password"
        assert code(fn("/api/users/me/password", json={"current_password": PW, "new_password": PW})) == "same_password"
        assert code(fn("/api/users/me/password", json={"current_password": PW, "new_password": "short"})) == "weak_password"
        ok = fn("/api/users/me/password", json={"current_password": PW, "new_password": "Brand#New99"})
        assert ok.status_code == 204 and ok.content == b""
        assert a.get("/api/auth/me").status_code == 200           # 本设备换发新 cookie
        assert code(other.get("/api/auth/me")) == "token_expired"  # 其他设备下线
        a.cookies.clear()
        assert a.post("/api/auth/login", json={"login": name, "password": "Brand#New99"}).status_code == 200


def test_password_change_lock(client):
    register(client)
    for _ in range(5):
        client.post("/api/users/me/password", json={"current_password": "Nope#1234", "new_password": "Brand#New99"})
    r = client.post("/api/users/me/password", json={"current_password": PW, "new_password": "Brand#New99"})
    assert r.status_code == 429 and code(r) == "rate_limited"


@pytest.mark.parametrize("path", ["/api/users/me", "/api/auth/me"])
def test_profile_patch_and_alias(client, path):
    register(client, email="p@x.com")
    r = client.patch(path, json={"nickname": "小雨", "bio": "喜欢民国悬疑"})
    assert r.status_code == 200 and r.json()["user"]["nickname"] == "小雨" and r.json()["user"]["bio"] == "喜欢民国悬疑"
    assert code(client.patch(path, json={"nickname": "长" * 21})) == "validation_error"
    assert code(client.patch(path, json={"bio": "x" * 201})) == "validation_error"
    assert code(client.patch(path, json={"email": "q@x.com"})) == "wrong_password"
    assert client.patch(path, json={"email": "q@x.com", "current_password": PW}).json()["user"]["email"] == "q@x.com"
    assert client.patch(path, json={"avatar_url": "preset:fox"}).json()["user"]["avatar_url"] == "preset:fox"
    assert code(client.patch(path, json={"avatar_url": "https://evil/x.png"})) == "validation_error"


def test_profile_requires_real_login_even_in_mode0(client):
    assert code(client.patch("/api/users/me", json={"nickname": "x"})) == "unauthorized"
    assert code(client.post("/api/users/me/password", json={})) == "unauthorized"
    assert client.get("/api/users/me/preferences").status_code == 200  # 偏好/统计在模式 0 下作用于 demo


def test_demo_account_readonly(core_env, monkeypatch):
    setenv(monkeypatch, ZM_DEMO_PASSWORD="Demo#Pass2026")
    from app import db
    db.reset_engine()
    with new_client() as c:
        r = c.post("/api/auth/login", json={"login": "demo", "password": "Demo#Pass2026"})
        assert r.status_code == 200 and r.json()["user"]["is_demo"] is True
        assert code(c.patch("/api/users/me", json={"nickname": "x"})) == "demo_readonly"
        assert code(c.post("/api/users/me/password", json={"current_password": "Demo#Pass2026",
                                                          "new_password": "Other#Pass99"})) == "demo_readonly"
        assert c.patch("/api/users/me/preferences", json={"tts_enabled": False}).status_code == 200


def test_avatar_upload(client):
    from PIL import Image
    import io
    register(client)
    r = client.post("/api/users/me/avatar", files={"file": ("a.png", png_bytes(300, 120), "image/png")})
    assert r.status_code == 200, r.text
    url = r.json()["avatar_url"]
    assert url.startswith("/api/static/avatars/") and url.endswith(".webp") and r.json()["user"]["avatar_url"] == url
    img = client.get(url)
    assert img.status_code == 200
    im = Image.open(io.BytesIO(img.content))
    assert im.format == "WEBP" and im.size == (256, 256)
    # 换头像删除旧文件
    r2 = client.post("/api/users/me/avatar", files={"file": ("b.jpg", png_bytes(50, 50, "JPEG"), "image/jpeg")})
    assert r2.status_code == 200 and client.get(url).status_code == 404
    assert code(client.post("/api/users/me/avatar", files={"file": ("x.gif", b"GIF89a....", "image/gif")})) \
        == "unsupported_media_type"
    assert code(client.post("/api/users/me/avatar", files={"file": ("x.png", b"\x89PNG\r\n\x1a\nbroken", "image/png")})) \
        == "invalid_image"
    big = png_bytes(10, 10) + b"\0" * (2 * 1024 * 1024)
    r = client.post("/api/users/me/avatar", files={"file": ("big.png", big, "image/png")})
    assert r.status_code == 413 and code(r) == "file_too_large"
    d = client.delete("/api/users/me/avatar")
    assert d.status_code == 200 and d.json()["avatar_url"] is None


def test_debug_status_requires_login_or_admin(core_env, monkeypatch):
    setenv(monkeypatch, ZM_ADMIN_TOKEN="adm-tok")
    with new_client() as c:
        assert code(c.get("/api/debug/status")) == "unauthorized"
        r = c.get("/api/debug/status", headers={"X-Admin-Token": "adm-tok"})
        assert r.status_code == 200 and "multimodal" in r.json()
        assert c.get("/api/debug/status", headers={"X-Admin-Token": "wrong"}).status_code == 401
        register(c)
        assert c.get("/api/debug/status").status_code == 200
        assert c.get("/api/health").status_code == 200


def test_origin_check_on_cookie_writes(client):
    register(client)
    r = client.patch("/api/users/me", json={"nickname": "x1"}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and code(r) == "forbidden"
    assert client.patch("/api/users/me", json={"nickname": "x2"}, headers={"Origin": "http://localhost:3000"}).status_code == 200


# ---------------------------------------------------------------- 可信代理（AUTH-QA-1）
def test_client_ip_resolution(core_env, monkeypatch):
    from app.auth.middleware import client_ip
    setenv(monkeypatch, ZM_TRUSTED_PROXIES="127.0.0.1/32,::1,172.16.0.0/12")
    ip = lambda peer, **h: client_ip({"client": (peer, 1)}, {k.replace("_", "-"): v for k, v in h.items()})  # noqa: E731
    assert ip("172.18.0.3", x_forwarded_for="198.51.100.9") == "198.51.100.9"          # 可信网段 → XFF
    assert ip("172.18.0.3", x_forwarded_for="6.6.6.6, 198.51.100.9, 172.18.0.2") == "198.51.100.9"  # 右起第一个不可信
    assert ip("172.18.0.3", x_real_ip="198.51.100.10") == "198.51.100.10"
    assert ip("203.0.113.5", x_forwarded_for="1.2.3.4") == "203.0.113.5"               # 不可信对端：忽略伪造 XFF
    assert ip("203.0.113.5", x_real_ip="1.2.3.4") == "203.0.113.5"
    assert ip("::1", x_forwarded_for="2001:db8::7") == "2001:db8::7"
    setenv(monkeypatch, ZM_TRUST_PROXY=0)                                               # 兼容旧开关
    assert ip("127.0.0.1", x_forwarded_for="1.2.3.4") == "127.0.0.1"


def test_rate_limit_uses_resolved_ip(core_env, monkeypatch):
    setenv(monkeypatch, ZM_TRUSTED_PROXIES="127.0.0.1/32,10.0.0.0/8", ZM_REGISTER_PER_HOUR=2)
    with new_client("10.1.2.3") as proxy:   # 来自可信代理：按 XFF 区分用户
        for i in range(3):
            assert register(proxy, xff=f"198.51.100.{i + 1}")[0].status_code == 201
    with new_client("203.0.113.9") as direct:  # 不可信对端伪造不同 XFF 也绕不过限流
        assert register(direct, xff="1.1.1.1")[0].status_code == 201
        assert register(direct, xff="2.2.2.2")[0].status_code == 201
        assert register(direct, xff="3.3.3.3")[0].status_code == 429
    with new_client("10.1.2.3") as proxy:   # 同一真实 IP 经代理也会被限
        name = uname()
        assert register(proxy, xff="198.51.100.200")[0].status_code == 201
        register(proxy, xff="198.51.100.200")
        assert register(proxy, name, xff="198.51.100.200")[0].status_code == 429
