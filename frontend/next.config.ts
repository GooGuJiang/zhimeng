import type { NextConfig } from "next";

/**
 * The browser only ever talks to this Next app (same origin).
 * /api/* (incl. generated assets at /api/static/assets) is proxied to the FastAPI backend, so API keys stay server-side
 * and no CORS is needed. Override the target with BACKEND_ORIGIN.
 */
const BACKEND = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

/**
 * Rewrites are proxied by Next's httpxy proxy whose socket timeout defaults to 30 s; a slower backend
 * response (real-model 学习小结 / 世界生成 / 记忆问答 / 插画 / 配音, LLM retries) was cut with
 * "socket hang up" → 500 (BUG-007). It is an idle timeout, so SSE streams that keep emitting are fine.
 * Read by router-server in both `next dev` and `next start` (Next 16.4).
 */
const PROXY_TIMEOUT_MS = Number(process.env.ZM_PROXY_TIMEOUT_MS ?? 180_000);

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Do not gzip-buffer proxied Server-Sent Events.
  compress: false,
  experimental: { proxyTimeout: PROXY_TIMEOUT_MS },
  // Docker 构建时（frontend/Dockerfile 设置 NEXT_OUTPUT=standalone）输出独立服务器；本地 dev/start 不受影响
  ...(process.env.NEXT_OUTPUT === "standalone" ? { output: "standalone" as const } : {}),
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
  },
};

export default nextConfig;
