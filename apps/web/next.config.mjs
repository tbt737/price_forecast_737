/** @type {import('next').NextConfig} */

import { fileURLToPath } from "node:url";
import path from "node:path";

// Proxy the browser's same-origin /api/* calls to the FastAPI backend (server-side),
// so local dev needs NO CORS change on the backend. Override the target with
// API_PROXY_TARGET if the API runs elsewhere.
const API_PROXY_TARGET = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // The monorepo root also carries its own package-lock.json (Cloudflare Worker
  // wrapper, unrelated to this app), which makes Next.js guess the wrong workspace
  // root. Pin it explicitly to this app's directory.
  outputFileTracingRoot: path.dirname(fileURLToPath(import.meta.url)),
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_PROXY_TARGET}/:path*` }];
  },
};

export default nextConfig;
