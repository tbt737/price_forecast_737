# Next.js dashboard for Cloud Run. Build context = apps/web:
#   gcloud run deploy cqp-web --source apps/web ...
FROM node:20-slim
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# Next.js evaluates next.config rewrites at BUILD time, so the backend URL must be
# present then (a runtime env var would be ignored). Default matches local
# next.config; production / compose MUST pass --build-arg API_PROXY_TARGET=...
# (docker-compose.yml already does). Do not bake a live Cloud Run URL in here.
ARG API_PROXY_TARGET=http://127.0.0.1:8000
ENV API_PROXY_TARGET=${API_PROXY_TARGET}

# Install deps (incl. dev deps — needed to run `next build`; NODE_ENV must NOT be
# 'production' here or npm ci would omit devDependencies).
COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

ENV NODE_ENV=production
EXPOSE 3000
# Cloud Run injects $PORT (8080); next.config reads API_PROXY_TARGET at runtime to
# proxy /api/* to the backend Cloud Run service.
CMD ["sh", "-c", "npx next start -p ${PORT:-3000}"]
