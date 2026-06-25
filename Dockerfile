# FastAPI forecast service. Lives at the repo root so the build context is the whole
# repo (it COPYs ml/, etl/, configs/, apps/api/). Works as-is with
# `docker build -t cqp-api .`, Cloud Run `--source .`, and Cloudflare Containers.
FROM python:3.13-slim

# Build tools for numpy/scipy/xgboost wheels are usually unnecessary (manylinux
# wheels exist), but keep libgomp for xgboost's OpenMP runtime.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "uvicorn[standard]>=0.29"

# Only the runtime code + config the API touches (no data/, no .env — secrets come
# from the host's environment).
COPY ml/ ./ml/
COPY etl/ ./etl/
COPY db/ ./db/
COPY configs/ ./configs/
COPY apps/api/ ./apps/api/

# main.py adds the repo root (/app) to sys.path so the root-level `ml` package
# imports; PYTHONPATH makes the `app` package (apps/api/app) importable.
ENV PYTHONPATH=/app/apps/api

EXPOSE 8000
# DATABASE_URL must be provided by the host as an environment variable.
# $PORT is honoured by hosts that inject it (Cloud Run=8080, Render/Fly, etc.); default 8000.
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
