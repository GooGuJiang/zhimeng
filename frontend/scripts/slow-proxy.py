#!/usr/bin/env python3
"""Dev tool: a pass-through proxy in front of the backend that delays selected paths, to test
long-running requests through the Next /api proxy (BUG-007).

  python3 frontend/scripts/slow-proxy.py --port 8020 --target http://localhost:8000 \
      --delay 35 --match /education/summary,/memory/query

Streams responses chunk-by-chunk, so SSE endpoints keep streaming through it.
"""
import argparse
import http.client
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8020)
ap.add_argument("--target", default="http://localhost:8000")
ap.add_argument("--delay", type=float, default=25.0)
ap.add_argument("--match", default="/education/summary")
args = ap.parse_args()
T = urllib.parse.urlparse(args.target)
MATCH = [m for m in args.match.split(",") if m]
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization", "proxy-authenticate"}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _go(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        if any(m in self.path for m in MATCH):
            self.log_message("delaying %s by %ss", self.path, args.delay)
            time.sleep(args.delay)
        c = http.client.HTTPConnection(T.hostname, T.port or 80, timeout=600)
        hdrs = {k: v for k, v in self.headers.items() if k.lower() not in HOP and k.lower() != "host"}
        c.request(self.command, self.path, body=body, headers=hdrs)
        r = c.getresponse()
        self.send_response(r.status, r.reason)
        for k, v in r.getheaders():
            if k.lower() not in HOP and k.lower() != "content-length":
                self.send_header(k, v)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        while True:
            chunk = r.read1(65536) if hasattr(r, "read1") else r.read(4096)
            if not chunk:
                break
            self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        c.close()

    do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = _go


ThreadingHTTPServer(("127.0.0.1", args.port), H).serve_forever()
