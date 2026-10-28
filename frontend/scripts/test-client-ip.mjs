/**
 * AUTH-QA-3 integration check: a real Next server (with scripts/client-ip-guard.cjs preloaded) in front of an
 * echo backend. Asserts that client-supplied X-Forwarded-For / X-Real-IP / Forwarded never reach the backend,
 * that only ZM_TRUST_PROXY=1 adopts the upstream's last hop, and that the /api proxy still streams SSE, passes
 * multiple Set-Cookie, Origin/Cookie, request bodies and 204s.
 *   pnpm test:client-ip                         # next dev
 *   ZM_GUARD_TARGET=standalone pnpm test:client-ip   # .next/standalone/server.js (after NEXT_OUTPUT=standalone build)
 * Uses free ephemeral ports only; no model calls.
 */
import http from "node:http";
import net from "node:net";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const TARGET = process.env.ZM_GUARD_TARGET ?? "dev";
const seen = [];

function freePort() {
  return new Promise((ok) => {
    const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => ok(p)); });
  });
}

const echo = http.createServer((req, res) => {
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    const h = req.headers;
    seen.push({ url: req.url, xff: h["x-forwarded-for"], real: h["x-real-ip"], fwd: h["forwarded"], cf: h["cf-connecting-ip"] });
    if (req.url.startsWith("/api/sse")) {
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", "x-accel-buffering": "no" });
      res.write("event: a\ndata: first\n\n");
      setTimeout(() => res.end("event: b\ndata: second\n\n"), 1500);
      return;
    }
    if (req.url.startsWith("/api/cookies")) {
      res.writeHead(200, [["set-cookie", "zm_access=a; HttpOnly; Path=/"], ["set-cookie", "zm_refresh=r; HttpOnly; Path=/api/auth"], ["content-type", "application/json"]]);
      return res.end("{}");
    }
    if (req.url.startsWith("/api/nocontent")) { res.writeHead(204); return res.end(); }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ method: req.method, body, origin: h.origin ?? null, cookie: h.cookie ?? null, xff: h["x-forwarded-for"] ?? null, real: h["x-real-ip"] ?? null, fwd: h.forwarded ?? null }));
  });
});

async function startNext(port, backend, extraEnv, withGuard = true) {
  const env = { ...process.env, BACKEND_ORIGIN: backend, PORT: String(port), HOSTNAME: "127.0.0.1", NEXT_TELEMETRY_DISABLED: "1", ...extraEnv };
  const guard = path.join(ROOT, "scripts/client-ip-guard.cjs");
  let child;
  if (TARGET === "standalone") {
    child = spawn(process.execPath, [...(withGuard ? ["--require", guard] : []), path.join(ROOT, ".next/standalone/server.js")], { env, stdio: "pipe" });
  } else {
    if (withGuard) env.NODE_OPTIONS = `--require ${guard} ${process.env.NODE_OPTIONS ?? ""}`;
    child = spawn(require.resolve("next/dist/bin/next"), ["dev", "-p", String(port), "-H", "127.0.0.1"], { cwd: ROOT, env, stdio: "pipe" });
  }
  let log = "";
  child.stdout.on("data", (d) => (log += d));
  child.stderr.on("data", (d) => (log += d));
  for (let i = 0; i < 120; i++) {
    try { const r = await fetch(`http://127.0.0.1:${port}/api/echo?ready`); if (r.ok) return child; } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  child.kill("SIGTERM");
  throw new Error(`next did not come up:\n${log}`);
}

const SPOOF = { "x-forwarded-for": "6.6.6.6", "x-real-ip": "6.6.6.7", forwarded: "for=6.6.6.8", "cf-connecting-ip": "6.6.6.9" };

async function main() {
  // pure function first
  const { clientIp } = require(path.join(ROOT, "scripts/client-ip.cjs")); // the library only: must NOT patch this process (echo sees raw headers)
  assert.equal(clientIp("::ffff:10.1.2.3", { "x-forwarded-for": "6.6.6.6" }, false), "10.1.2.3");
  assert.equal(clientIp("10.0.0.2", { "x-forwarded-for": "6.6.6.6, 203.0.113.7" }, true), "203.0.113.7");
  assert.equal(clientIp("10.0.0.2", { "x-forwarded-for": "6.6.6.6, not-an-ip" }, true), "10.0.0.2");
  assert.equal(clientIp("10.0.0.2", {}, true), "10.0.0.2");

  // standalone bakes the rewrite target at build time → build with BACKEND_ORIGIN=http://127.0.0.1:$ZM_ECHO_PORT
  const ep = Number(process.env.ZM_ECHO_PORT) || (await freePort());
  await new Promise((ok) => echo.listen(ep, "127.0.0.1", ok));
  const backend = `http://127.0.0.1:${ep}`;
  const failures = [];
  const check = async (name, fn) => {
    try { await fn(); console.log(`  ✓ ${name}`); } catch (e) { failures.push(name); console.log(`  ✘ ${name}\n    ${e.message}`); }
  };

  // 0) control: the same server WITHOUT the guard really does forward a spoofed header (what AUTH-QA-3 found)
  let port = await freePort();
  let next = await startNext(port, backend, { ZM_TRUST_PROXY: "" }, false);
  console.log(`[${TARGET}] control, no guard, on :${port}`);
  try {
    await check("control: without the guard a spoofed X-Forwarded-For reaches the backend", async () => {
      const j = await (await fetch(`http://127.0.0.1:${port}/api/echo`, { headers: SPOOF })).json();
      assert.equal(j.xff, "6.6.6.6");
      assert.equal(j.real, "6.6.6.7");
    });
  } finally { next.kill("SIGTERM"); await new Promise((r) => setTimeout(r, 800)); }

  // 1) default: trust nobody
  port = await freePort();
  next = await startNext(port, backend, { ZM_TRUST_PROXY: "" });
  const web = `http://127.0.0.1:${port}`;
  console.log(`[${TARGET}] default (ZM_TRUST_PROXY unset) on :${port} → echo :${ep}`);
  try {
    await check("echo backend sees raw headers (sanity: the guard is not installed in the test process)", async () => {
      const r = await fetch(`${backend}/api/echo`, { headers: { "x-forwarded-for": "6.6.6.6" } });
      assert.equal((await r.json()).xff, "6.6.6.6");
    });
    await check("spoofed X-Forwarded-For / X-Real-IP / Forwarded / CF-Connecting-IP never reach the backend", async () => {
      const j = await (await fetch(`${web}/api/echo`, { headers: SPOOF })).json();
      assert.equal(j.xff, "127.0.0.1");
      assert.equal(j.real, null);
      assert.equal(j.fwd, null);
      assert.ok(!JSON.stringify(seen.at(-1)).includes("6.6.6."), JSON.stringify(seen.at(-1)));
    });
    await check("comma-chained spoof is replaced too (backend takes the rightmost hop)", async () => {
      const j = await (await fetch(`${web}/api/echo`, { headers: { "x-forwarded-for": "1.1.1.1, 6.6.6.6" } })).json();
      assert.equal(j.xff, "127.0.0.1");
    });
    await check("no client header → X-Forwarded-For is the TCP peer (not the frontend's own address only by accident)", async () => {
      const j = await (await fetch(`${web}/api/echo`)).json();
      assert.equal(j.xff, "127.0.0.1");
    });
    await check("POST body, Origin and Cookie pass through", async () => {
      const r = await fetch(`${web}/api/echo`, { method: "POST", body: JSON.stringify({ a: 1 }), headers: { "content-type": "application/json", origin: web, cookie: "zm_access=x" } });
      const j = await r.json();
      assert.deepEqual([j.method, j.body, j.origin, j.cookie], ["POST", '{"a":1}', web, "zm_access=x"]);
    });
    await check("multiple Set-Cookie headers survive", async () => {
      const r = await fetch(`${web}/api/cookies`);
      assert.deepEqual(r.headers.getSetCookie().map((c) => c.split("=")[0]), ["zm_access", "zm_refresh"]);
    });
    await check("204 stays 204", async () => {
      const r = await fetch(`${web}/api/nocontent`, { method: "POST", headers: { origin: web } });
      assert.equal(r.status, 204);
    });
    await check("SSE is streamed, not buffered (first event arrives before the stream ends)", async () => {
      const t0 = Date.now();
      const r = await fetch(`${web}/api/sse`, { headers: SPOOF });
      const reader = r.body.getReader();
      const first = new TextDecoder().decode((await reader.read()).value);
      const tFirst = Date.now() - t0;
      let rest = "";
      for (;;) { const { done, value } = await reader.read(); if (done) break; rest += new TextDecoder().decode(value); }
      assert.ok(first.includes("first"), first);
      assert.ok(tFirst < 1200, `first event after ${tFirst}ms`);
      assert.ok(rest.includes("second"));
      assert.equal(seen.at(-1).xff, "127.0.0.1");
    });
  } finally { next.kill("SIGTERM"); await new Promise((r) => setTimeout(r, 800)); }

  // 2) explicitly behind our own reverse proxy
  port = await freePort();
  next = await startNext(port, backend, { ZM_TRUST_PROXY: "1" });
  console.log(`[${TARGET}] ZM_TRUST_PROXY=1 on :${port}`);
  try {
    await check("ZM_TRUST_PROXY=1: only the upstream's last hop is used; X-Real-IP / Forwarded still dropped", async () => {
      const j = await (await fetch(`http://127.0.0.1:${port}/api/echo`, { headers: { ...SPOOF, "x-forwarded-for": "6.6.6.6, 203.0.113.7" } })).json();
      assert.deepEqual([j.xff, j.real, j.fwd], ["203.0.113.7", null, null]);
    });
    await check("ZM_TRUST_PROXY=1 without upstream XFF → TCP peer", async () => {
      const j = await (await fetch(`http://127.0.0.1:${port}/api/echo`)).json();
      assert.equal(j.xff, "127.0.0.1");
    });
  } finally { next.kill("SIGTERM"); }

  echo.close();
  console.log(failures.length ? `${failures.length} failed` : "all passed");
  process.exit(failures.length ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(1); });
