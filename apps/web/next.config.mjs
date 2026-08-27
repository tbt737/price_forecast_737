/** @type {import('next').NextConfig} */

import { fileURLToPath } from "node:url";

// Proxy the browser's same-origin /api/* calls to the FastAPI backend (server-side),
// so local dev needs NO CORS change on the backend. Override the target with
// API_PROXY_TARGET if the API runs elsewhere.
const API_PROXY_TARGET = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // The repo root also carries a package-lock.json (Cloudflare Worker wrapper), so
  // Next.js can't infer this workspace's root from lockfiles alone — pin it here to
  // silence the "multiple lockfiles" warning and keep file tracing scoped to apps/web.
  outputFileTracingRoot: fileURLToPath(new URL(".", import.meta.url)),
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_PROXY_TARGET}/:path*` }];
  },
};

export default nextConfig;
