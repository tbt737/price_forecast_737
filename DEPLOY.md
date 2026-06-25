# DEPLOY — going live

Recommended stack:

| Layer | Host | Notes |
| ----- | ---- | ----- |
| Database | **Supabase** (already used) | Already holds the data. Supabase can ONLY be the DB — its Edge Functions run Deno/TS, not this Python service. |
| Backend (FastAPI + ML) | **Google Cloud Run** | Runs the root `Dockerfile`. Configurable CPU (1–2 vCPU → faster forecasts than the alternatives), generous always-free tier, GA/stable, scale-to-zero. |
| Frontend (Next.js) | **Cloudflare Pages** | Native Next.js hosting (free). |

> Alternatives for the backend (same `Dockerfile`, unchanged): **Cloudflare
> Containers** (all-Cloudflare, but Workers Paid $5/mo + 0.5 vCPU + open beta) or
> **Render / Railway / Fly.io**. Cloud Run is recommended: more CPU for the
> CPU-heavy XGBoost forecast, likely $0 on the free tier, and battle-tested.

The image is verified: `docker build -t cqp-api .` builds and the container serves
real forecasts against Supabase (`$PORT`-aware, so it drops into Cloud Run as-is).

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

## 1. Backend → Google Cloud Run (recommended)

Easiest with **Cloud Shell** (browser — `gcloud`, `docker`, `git` pre-installed, no
local install). Open <https://shell.cloud.google.com>, then:

```bash
git clone https://github.com/tbt737/price_forecast_737.git
cd price_forecast_737

gcloud config set project <YOUR_PROJECT_ID>
gcloud services enable run.googleapis.com cloudbuild.googleapis.com

gcloud run deploy cqp-api \
  --source . \
  --region asia-northeast1 \            # Tokyo = same region as Supabase
  --memory 2Gi --cpu 2 \
  --timeout 120 \
  --allow-unauthenticated \
  --set-env-vars "DATABASE_URL=<SUPABASE_SESSION_POOLER_URL>"   # the pooler URL, step 0
```

`--source .` makes Cloud Build build the root `Dockerfile` (the first deploy takes a
few minutes). Cloud Run injects `PORT=8080`, which the Dockerfile honours. The
command prints the service URL, e.g. `https://cqp-api-xxxx.asia-northeast1.run.app`.

- To kill cold starts, add `--min-instances 1` (small always-on cost).
- Prefer not to put the secret on the command line? Omit `--set-env-vars`, then set
  `DATABASE_URL` in the Cloud Run console (Edit & deploy → Variables & Secrets) or
  via Secret Manager.

## 1-ALT. Backend → Cloudflare Containers ($5/mo, all-Cloudflare)

The Worker that fronts the container is already in the repo: `wrangler.jsonc`,
`worker/index.js` (the `ApiContainer` class + request forwarder) and `package.json`.
The container uses `Dockerfile` with the **repo root as build context**
(`image_build_context: "."`) and the **`standard-1`** instance (1/2 vCPU, 4 GiB).

From the repo root:

1. `npm install` — pulls `wrangler` + `@cloudflare/containers`.
2. `npx wrangler login` — log into your Cloudflare account.
3. `npx wrangler secret put DATABASE_URL` — paste the **Session pooler** URL (step 0).
   `worker/index.js` injects it into the container's environment.
4. `npx wrangler deploy` — Wrangler builds the Dockerfile, pushes the image, and
   deploys the Worker. Note the URL, e.g. `https://cqp-api.<account>.workers.dev`.
   Health check: `/health`.

> Prefer always-on / no cold start? The same `Dockerfile` runs unchanged on
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
  update the backend's env var (Cloud Run) + the GitHub Actions secret.
