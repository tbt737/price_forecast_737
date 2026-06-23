/**
 * Frontend config. The browser always calls the same-origin `/api` prefix;
 * Next rewrites it to the FastAPI backend server-side (see next.config.mjs),
 * so no secret or absolute backend URL is needed in the client bundle.
 */
export const API_BASE = "/api";
