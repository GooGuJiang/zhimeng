/**
 * AUTH-QA-3 — the client IP the backend sees must come from the TCP socket, never from the client.
 *
 * Why a preload and not next.config rewrites / a route handler (checked against Next 16.4 source):
 *  - base-server.js only does `req.headers['x-forwarded-for'] ??= socket.remoteAddress`, so a client-supplied
 *    X-Forwarded-For wins, and the rewrite proxy (router-utils/proxy-request.js → httpxy, no `xfwd`) forwards
 *    request headers unchanged. Rewrites have no hook to drop or overwrite headers.
 *  - App Router route handlers / proxy.ts only see a Web `Request`: no socket, and the header is already the
 *    spoofed value, so a /api/[...path] handler could not recover the real peer either.
 * So we sanitize on the Node http server itself, before Next handles the request, and keep the rewrite proxy
 * (SSE stays unbuffered, 180 s proxyTimeout, multi Set-Cookie, Origin/Cookie, streamed bodies, 204 all unchanged).
 *
 * Rules: drop every client-IP header (X-Forwarded-For, X-Real-IP, Forwarded, …) and set exactly one
 * `X-Forwarded-For: <client>`, where client = TCP peer address. Only with ZM_TRUST_PROXY=1 (this app runs behind
 * our own reverse proxy, e.g. nginx in front of docker) is the LAST hop of the upstream X-Forwarded-For used —
 * that is the hop our proxy appended; anything to its left is client-controlled. Default: trust nobody.
 *
 * This file only defines the logic; scripts/client-ip-guard.cjs is the preload that installs it
 * (`node -r ./scripts/client-ip-guard.cjs …` in package.json dev/start and the Dockerfile CMD).
 */
"use strict";
const http = require("http");
const net = require("net");

const CLIENT_IP_HEADERS = [
  "x-forwarded-for", "x-real-ip", "forwarded", "x-client-ip", "true-client-ip", "cf-connecting-ip",
  "x-cluster-client-ip", "fastly-client-ip", "x-original-forwarded-for", "x-forwarded",
];
const DROP = new Set(CLIENT_IP_HEADERS);

function normIp(v) {
  if (typeof v !== "string") return null;
  let s = v.trim();
  if (s.startsWith("[") && s.includes("]")) s = s.slice(1, s.indexOf("]")); // [v6]:port
  else if (/^\d+\.\d+\.\d+\.\d+:\d+$/.test(s)) s = s.slice(0, s.lastIndexOf(":")); // v4:port
  if (s.toLowerCase().startsWith("::ffff:") && net.isIPv4(s.slice(7))) s = s.slice(7);
  return net.isIP(s) ? s : null;
}

/** The address to forward for this request (pure; exported for tests). */
function clientIp(peer, headers, trustProxy) {
  const direct = normIp(peer) ?? "0.0.0.0";
  if (!trustProxy) return direct;
  const raw = headers["x-forwarded-for"];
  const chain = (Array.isArray(raw) ? raw.join(",") : raw ?? "").split(",").map((x) => x.trim()).filter(Boolean);
  return (chain.length && normIp(chain[chain.length - 1])) || direct;
}

function sanitize(req, trustProxy) {
  const ip = clientIp(req.socket && req.socket.remoteAddress, req.headers, trustProxy);
  for (const h of CLIENT_IP_HEADERS) delete req.headers[h];
  req.headers["x-forwarded-for"] = ip;
  if (Array.isArray(req.rawHeaders)) {
    const raw = [];
    for (let i = 0; i < req.rawHeaders.length; i += 2) {
      if (!DROP.has(String(req.rawHeaders[i]).toLowerCase())) raw.push(req.rawHeaders[i], req.rawHeaders[i + 1]);
    }
    raw.push("X-Forwarded-For", ip);
    req.rawHeaders.length = 0;
    req.rawHeaders.push(...raw);
  }
  return ip;
}

const PATCHED = Symbol.for("zhimeng.clientIpGuard");
function install(trustProxy = process.env.ZM_TRUST_PROXY === "1") {
  if (http.Server.prototype[PATCHED]) return;
  const emit = http.Server.prototype.emit;
  http.Server.prototype.emit = function (event, req, ...rest) {
    if ((event === "request" || event === "upgrade") && req && req.headers) sanitize(req, trustProxy);
    return emit.call(this, event, req, ...rest);
  };
  http.Server.prototype[PATCHED] = true;
}

module.exports = { clientIp, sanitize, install, CLIENT_IP_HEADERS };
