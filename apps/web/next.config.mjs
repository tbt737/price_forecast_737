/** @type {import('next').NextConfig} */

import path from "node:path";
import { fileURLToPath } from "node:url";

// Proxy the browser's same-origin /api/* calls to the FastAPI backend (server-side),
// so local dev needs NO CORS change on the backend. Override the target with
// API_PROXY_TARGET if the API runs elsewhere.
const API_PROXY_TARGET = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

// Root package-lock.json belongs to the Cloudflare Worker, not this app.
// Pin tracing to apps/web so Next does not treat the repo root as the workspace.
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const nextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: __dirname,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_PROXY_TARGET}/:path*` }];
  },
};

export default nextConfig;
