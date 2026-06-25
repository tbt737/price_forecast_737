# DEPLOY — going live

Recommended stack — **Supabase + Cloudflare** (one ecosystem, scale-to-zero):

| Layer | Host | Notes |
| ----- | ---- | ----- |
| Database | **Supabase** (already used) | Nothing to do — it already holds the data. Supabase can ONLY be the DB: its Edge Functions run Deno/TS, not this Python service. |
| Backend (FastAPI + ML) | **Cloudflare Containers** | Runs `apps/api/Dockerfile` (Python/Docker, up to 4 GiB RAM / 0.5 vCPU, scale-to-zero). Available since June 2025. |
| Frontend (Next.js) | **Cloudflare Pages** | Native Next.js hosting. |

> Render / Railway / Fly.io also run the same Dockerfile if you ever want a
> dedicated always-on backend — but Cloudflare Containers covers it now, so the
> whole app is Supabase (DB) + Cloudflare (frontend + backend).

The API image is verified: `docker build -f apps/api/Dockerfile -t cqp-api .` builds,
and the container serves real forecasts against Supabase. It is `linux/amd64`
(Cloudflare Containers' required arch).

**Cloudflare Containers caveats:** 0.5 vCPU makes a cold forecast (~6–9s) a little
slower, but the response cache makes repeat calls instant; scale-to-zero adds a
~15–20s cold start on the first request after idle; disks are ephemeral (fine — all
state is in Supabase).

---

## 0. ⚠️ The one thing that always bites: use the Supabase **pooler** URL

Supabase's *direct* host (`db.<ref>.supabase.co`) resolves to **IPv6**, which most
container/CI networks (Docker, Render, GitHub Actions) **cannot reach** — you'll see
`connection to server at "2406:…", port 5432 failed: Network is unreachable`.

Use the **Session pooler** connection string (IPv4) instead. In Supabase:
**Project → Connect → Session pooler**. It looks like:

```
postgresql+psycopg://postgres.<ref>:<PASSWORD>@aws-1-<region>.pooler.supabase.com:5432/postgres
```

(Keep the `+psycopg` driver prefix; URL-encode the password: `@`→`%40`, `#`→`%23`.)

---

## 1. Backend → Cloudflare Containers

The Worker that fronts the container is already in the repo: `wrangler.jsonc`,
`worker/index.js` (the `ApiContainer` class + request forwarder) and `package.json`.
The container uses `apps/api/Dockerfile` with the **repo root as build context**
(`image_build_context: "."`) and the **`standard-1`** instance (1/2 vCPU, 4 GiB).

From the repo root:

1. `npm install` — pulls `wrangler` + `@cloudflare/containers`.
2. `npx wrangler login` — log into your Cloudflare account.
3. `npx wrangler secret put DATABASE_URL` — paste the **Session pooler** URL (step 0).
   `worker/index.js` injects it into the container's environment.
4. `npx wrangler deploy` — Wrangler builds the Dockerfile, pushes the image, and
   deploys the Worker. Note the URL, e.g. `https://cqp-api.<account>.workers.dev`.
   Health check: `/health`.

> Prefer always-on / no cold start? The same `apps/api/Dockerfile` runs unchanged on
> Render / Railway / Fly.io — set `DATABASE_URL` (pooler) and deploy.

## 2. Frontend → Cloudflare Pages

1. Cloudflare dashboard → **Workers & Pages → Create → Pages → Connect to Git** → this
   repo → **Root directory: `apps/web`**, framework preset **Next.js**.
2. Environment variable `API_PROXY_TARGET` = the backend URL from step 1.
   `next.config` rewrites `/api/*` to it.
3. Deploy. Pages gives you the public site URL (`*.pages.dev`).

## 3. Keep data fresh

The daily ingest already runs via **GitHub Actions** (`.github/workflows/ingest.yml`,
22:00 UTC) using the `DATABASE_URL` repo secret (also the pooler URL). Yahoo-backed
futures stay current automatically; the Indian-produce series are frozen at the latest
Kaggle dump until a newer one is imported (no live mandi feed reachable).

## 4. Smoke test

```
curl https://<backend>/health
curl https://<backend>/stats                      # 18 commodities / 63 instruments
curl https://<backend>/commodities/GOLD/forecast  # first call ~5–9s, then cached
```
Then open the Pages URL → Commodity Explorer should show real prices + forecasts, and
the "⚖ So sánh hàng hóa" compare view should work.

## Security

- Never commit `.env` (gitignored). Set `DATABASE_URL` only in the host's env / secrets.
- The Supabase DB password appeared in chat during setup — rotate it (alphanumeric) and
  update the Render env var + the GitHub Actions secret.
