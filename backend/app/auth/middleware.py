"""AuthMiddleware（纯 ASGI，保证整个请求含 SSE 流都在同一个身份上下文里）。

1. 解析身份：合法 zm_access → 用户；带了但无效 → expired；没有 → 匿名（模式 0 = demo）。
2. 按路径执行鉴权（契约 §6）：公开 / 路由自理 / 必须真实登录 / 受保护（ZM_AUTH_REQUIRED 决定匿名是否放行）。
3. CSRF：带 zm_* cookie 的写请求若有 Origin，必须在 CORS 白名单内（或与 Host 同源）。
"""
from __future__ import annotations

import hmac
import ipaddress
from functools import lru_cache
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from app.auth.context import Identity, reset_identity, set_identity
from app.auth.errors import AuthError, token_expired, unauthorized
from app.config import get_settings

PUBLIC = {"/api/health", "/api/safety/policy", "/api/safety/check", "/api/auth/register", "/api/auth/login",
          "/api/auth/logout", "/api/auth/refresh"}
SELF_HANDLED = {"/api/auth/me", "/api/debug/status"}
ADMIN_OK = {"/api/reports"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _real_login_only(path: str, method: str) -> bool:
    return ((path == "/api/users/me" and method == "PATCH") or path.startswith("/api/users/me/password")
            or path.startswith("/api/users/me/avatar"))


def _headers(scope) -> dict[str, str]:  # noqa: ANN001
    out: dict[str, str] = {}
    for k, v in scope.get("headers") or []:
        name = k.decode("latin-1").lower()
        val = v.decode("latin-1")
        out[name] = f"{out[name]}; {val}" if name == "cookie" and name in out else val
    return out


def cookies_of(headers: dict[str, str]) -> dict[str, str]:
    c: SimpleCookie = SimpleCookie()
    try:
        c.load(headers.get("cookie", ""))
    except Exception:  # noqa: BLE001
        return {}
    return {k: m.value for k, m in c.items()}


@lru_cache(maxsize=16)
def _networks(spec: str) -> tuple:
    nets = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return tuple(nets)


def _ip(v: str):  # noqa: ANN202
    v = v.strip().strip('"')
    if v.startswith("[") and "]" in v:  # [v6]:port
        v = v[1:v.index("]")]
    elif v.count(":") == 1 and "." in v:  # v4:port
        v = v.split(":")[0]
    try:
        ip = ipaddress.ip_address(v)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip


def trusted(ip) -> bool:  # noqa: ANN001
    s = get_settings()
    if ip is None or not s.zm_trust_proxy:
        return False
    return any(ip.version == n.version and ip in n for n in _networks(s.zm_trusted_proxies))


def client_ip(scope, headers: dict[str, str]) -> str:  # noqa: ANN001
    """对端在 ZM_TRUSTED_PROXIES 内 → 采信 X-Forwarded-For（从右往左第一个不可信地址；全可信取最左）或 X-Real-IP；
    否则一律用对端地址（忽略伪造的 XFF）。限流与注册频率都按这里的结果计算。"""
    peer_raw = (scope.get("client") or ("", 0))[0] or ""
    peer = _ip(peer_raw)
    if not trusted(peer):
        return str(peer) if peer else (peer_raw or "unknown")
    chain = [x for x in headers.get("x-forwarded-for", "").split(",") if x.strip()]
    if chain:
        ips = [_ip(x) for x in chain]
        for ip in reversed(ips):
            if ip is None:
                break  # 无法解析的条目：不再往左信任
            if not trusted(ip):
                return str(ip)
        first = next((ip for ip in ips if ip is not None), None)
        return str(first) if first and all(ip is not None for ip in ips) else str(peer)
    real = _ip(headers.get("x-real-ip", ""))
    return str(real) if real else str(peer)


def _origin_ok(origin: str, headers: dict[str, str]) -> bool:
    o = origin.rstrip("/")
    if o in get_settings().cors_list:
        return True
    return bool(urlsplit(o).netloc) and urlsplit(o).netloc == headers.get("host", "")


def resolve(headers: dict[str, str]) -> Identity:
    from app.auth.security import ACCESS_COOKIE
    from app.auth.service import check_access

    s = get_settings()
    tok = headers.get("x-admin-token", "")
    admin = bool(s.zm_admin_token and tok and hmac.compare_digest(s.zm_admin_token, tok))
    access = cookies_of(headers).get(ACCESS_COOKIE, "")
    if access:
        hit = check_access(access)
        if hit:
            return Identity(user_id=hit[0].id, session_id=hit[1], anonymous=False, admin=admin)
        return Identity(anonymous=True, admin=admin, expired=True)
    return Identity(anonymous=True, admin=admin)


def gate(ident: Identity, path: str, method: str) -> None:
    """受保护路径的鉴权；不通过抛 AuthError。"""
    if path in PUBLIC or path in SELF_HANDLED or not path.startswith("/api/") or path.startswith("/api/static/"):
        return
    if method == "OPTIONS":
        return
    if ident.expired:
        raise token_expired()
    if ident.authenticated:
        return
    if ident.admin and path in ADMIN_OK:
        return
    if _real_login_only(path, method) or get_settings().zm_auth_required:
        raise unauthorized()


class AuthMiddleware:
    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api"):
            await self.app(scope, receive, send)
            return
        path, method = scope["path"].rstrip("/") or "/", scope.get("method", "GET").upper()
        headers = _headers(scope)
        try:
            if method not in SAFE_METHODS and headers.get("origin") and "zm_" in headers.get("cookie", "") \
                    and not _origin_ok(headers["origin"], headers):
                raise AuthError(403, "forbidden", "请求来源不被允许")
            public = path in PUBLIC or path.startswith("/api/static/")
            ident = Identity(anonymous=True) if public and path not in ("/api/auth/logout",) else resolve(headers)
            if public and ident.expired:
                ident = Identity(anonymous=True, admin=ident.admin)
            gate(ident, path, method)
        except AuthError as e:
            await e.response()(scope, receive, send)
            return
        scope.setdefault("state", {})["zm_ip"] = client_ip(scope, headers)
        tok = set_identity(ident)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_identity(tok)
