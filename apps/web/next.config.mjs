/** @type {import('next').NextConfig} */

import path from "node:path";

// Proxy the browser's same-origin /api/* calls to the FastAPI backend (server-side),
// so local dev needs NO CORS change on the backend. Override the target with
// API_PROXY_TARGET if the API runs elsewhere.
const API_PROXY_TARGET = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // This app has its own lockfile (apps/web/package-lock.json) alongside the repo-root
  // one (unrelated Cloudflare Worker package) — pin the root explicitly so Next.js
  // doesn't have to guess and warn on every lint/build.
  outputFileTracingRoot: path.join(import.meta.dirname, ".."),
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_PROXY_TARGET}/:path*` }];
  },
};

export default nextConfig;
