/** @type {import('next').NextConfig} */

// Proxy the browser's same-origin /api/* calls to the FastAPI backend (server-side),
// so local dev needs NO CORS change on the backend. Override the target with
// API_PROXY_TARGET if the API runs elsewhere.
const API_PROXY_TARGET = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // Repo root also has its own package-lock.json (Cloudflare Worker wrapper), so
  // Next.js can't infer the workspace root — pin it to apps/web to silence the
  // "multiple lockfiles" warning without touching either lockfile.
  outputFileTracingRoot: import.meta.dirname,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_PROXY_TARGET}/:path*` }];
  },
};

export default nextConfig;
