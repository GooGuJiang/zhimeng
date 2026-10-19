import type { NextConfig } from "next";

/**
 * The browser only ever talks to this Next app (same origin).
 * /api/* and /static/* are proxied to the FastAPI backend, so API keys stay server-side
 * and no CORS is needed. Override the target with BACKEND_ORIGIN.
 */
const BACKEND = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Do not gzip-buffer proxied Server-Sent Events.
  compress: false,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND}/api/:path*` },
      { source: "/static/:path*", destination: `${BACKEND}/static/:path*` },
    ];
  },
};

export default nextConfig;
