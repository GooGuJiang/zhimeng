#!/usr/bin/env python3
"""AUTH-QA-3 端到端探针：经前端代理（及可选直连后端）验证伪造 XFF 绕不过限流，并记录同源共享按 IP 额度的影响。

  python3 scripts/qa_xff_probe.py --web http://127.0.0.1:3140 [--api http://127.0.0.1:8140] [--shared-quota] [--register-quota]

--api 只在「后端看到的对端不在 ZM_TRUSTED_PROXIES」时有意义（如 Docker 下经宿主端口直连后端）；
本机 dev（对端 127.0.0.1 默认可信）直连后端时 XFF 会被采信，这是设计如此（后端只给本机进程）。
会注册若干 xq* 账号并制造登录失败，--shared-quota 会把探针来源锁 15 分钟、--register-quota 会用完该来源本小时的注册额度：只在测试环境运行。不读取、不打印密钥。"""
import argparse, json, random, string, sys, urllib.error, urllib.request

PW = "Qa-Pass-2026x"
results = []


def req(base, path, body=None, xff=None, origin=None):
    h = {"Content-Type": "application/json"}
    if xff:  # 一次带齐常见的客户端 IP 头，全部应被前端丢弃
        h.update({"X-Forwarded-For": xff, "X-Real-IP": xff, "Forwarded": f"for={xff}"})
    if origin:
        h["Origin"] = origin
    r = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), headers=h,
                               method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def uname():
    return "xq" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def fake(i):
    return f"203.0.113.{i % 250 + 1}"


def check(label, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label + (f"  [{detail}]" if detail else ""), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", required=True)
    ap.add_argument("--api")
    ap.add_argument("--shared-quota", action="store_true")
    ap.add_argument("--register-quota", action="store_true")
    a = ap.parse_args()
    web = a.web.rstrip("/")

    def register(base, xff=None):
        n = uname()
        s, b = req(base, "/api/auth/register", {"username": n, "password": PW, "nickname": "探针"}, xff, web)
        return n, s, b

    def login(base, n, pw, xff=None):
        return req(base, "/api/auth/login", {"login": n, "password": pw}, xff, web)

    n1, s, b = register(web, fake(0))
    check("前端代理：注册", s == 201, f"{s} {b[:80]}")
    codes = [login(web, n1, "Wrong-pass-1", fake(i + 1))[0] for i in range(5)]
    s6, b6 = login(web, n1, PW, fake(99))
    check("前端代理：每次换伪造 XFF/X-Real-IP/Forwarded，5 次失败后正确密码仍 429（IP+账号规则生效）",
          codes == [401] * 5 and s6 == 429, f"{codes} -> {s6} {b6[:90]}")
    n2, s, _ = register(web)
    s2, _ = login(web, n2, PW, fake(7))
    check("前端代理：同一来源下另一账号不受影响", s == 201 and s2 == 200, f"{s}/{s2}")
    if a.api:
        api = a.api.rstrip("/")
        m1, s, b = register(api, fake(10))
        check("直连后端：注册", s == 201, f"{s} {b[:80]}")
        codes = [login(api, m1, "Wrong-pass-1", fake(i + 20))[0] for i in range(5)]
        s6, _ = login(api, m1, PW, fake(98))
        check("直连后端：对端不可信，伪造 XFF 被忽略（5 次失败后 429）", codes == [401] * 5 and s6 == 429, f"{codes} -> {s6}")
    if a.shared_quota:
        # 同源（如 Docker 网关 / NAT 后的所有人）共享每 IP 额度：用不存在的用户名累计 20 次失败（不消耗注册额度），
        # 之后同源的无关账号 n2 用正确密码登录 → 契约 §5「同一 IP 15 分钟失败 20 次锁 15 分钟」
        for i in range(20):
            login(web, uname(), "Wrong-pass-1", fake(i))
        s, b = login(web, n2, PW)
        check("同源累计 20 次失败后，同源无关账号也被锁 15 分钟（每 IP 规则 = 同源共享额度；记录影响）", s == 429, f"{s} {b[:90]}")
    if a.register_quota:
        ok = 0
        for _ in range(12):
            _, s, b = register(web, fake(ok))
            if s != 201:
                break
            ok += 1
        print(f"INFO 同源每小时注册：本轮又成功 {ok} 次后返回 {s} {b[:90]}（每 IP 10 次/小时，同源所有人共享）", flush=True)
    print(f"\n{sum(results)}/{len(results)} PASS")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
