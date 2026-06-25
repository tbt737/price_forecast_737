# DEPLOY — going live

Recommended stack (each has a free/low-cost tier):

| Layer | Host | Notes |
| ----- | ---- | ----- |
| Database | **Supabase** (already used) | Nothing to do — it already holds the data. |
| Backend (FastAPI) | **Render** (or Railway / Fly.io) | Builds `apps/api/Dockerfile`. |
| Frontend (Next.js) | **Vercel** | Native Next.js; just point it at the backend URL. |

The API image is verified: `docker build -f apps/api/Dockerfile -t cqp-api .` builds,
and the container serves real forecasts against Supabase.

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

## 1. Backend → Render

1. Push this repo to GitHub (already done: `master`).
2. Render → **New → Web Service** → connect the repo.
3. **Runtime: Docker**, Dockerfile path `apps/api/Dockerfile`, build context = repo root.
4. **Environment variable** `DATABASE_URL` = the **Session pooler** URL (step 0).
5. Instance: the image loads xgboost + pandas + PyWavelets and a forecast peaks ~0.5 GB
   RAM — pick at least a **512 MB** instance (Render free is borderline; the Starter
   plan is safer). Forecasts are cached, so steady-state RAM is low.
6. Deploy. Health check path: `/health`. Note the public URL, e.g.
   `https://cqp-api.onrender.com`.

> Railway/Fly.io work the same way — they all consume `apps/api/Dockerfile` and the
> `DATABASE_URL` env var; Fly's default 256 MB VM should be bumped to 512 MB.

## 2. Frontend → Vercel

1. Vercel → **New Project** → import the repo → **Root Directory: `apps/web`**.
2. Environment variable `API_PROXY_TARGET` = the backend URL from step 1
   (e.g. `https://cqp-api.onrender.com`). `next.config` rewrites `/api/*` to it.
3. Deploy. Vercel gives you the public site URL.

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
Then open the Vercel URL → Commodity Explorer should show real prices + forecasts, and
the "⚖ So sánh hàng hóa" compare view should work.

## Security

- Never commit `.env` (gitignored). Set `DATABASE_URL` only in the host's env / secrets.
- The Supabase DB password appeared in chat during setup — rotate it (alphanumeric) and
  update the Render env var + the GitHub Actions secret.
