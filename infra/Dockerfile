# Rețeaua Vie image: FastAPI on :3000 (frontend at /, API at /api) plus the system
# tools the pipeline needs: Java 21 (r5py, GTFS-RT validator), osmium (OSM),
# Pango/HarfBuzz and Noto fonts (WeasyPrint poster).
# Build from the repo root: docker build -f infra/Dockerfile .   (or `make up`)
# Data and secrets are never baked in: $DATA_DIR is a volume and the env file
# comes from compose (env_file).
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3.12 ca-certificates tzdata \
      openjdk-21-jre-headless osmium-tool \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-noto-core \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV UV_PYTHON=python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

WORKDIR /app/backend
# Dependencies first, so a code change does not reinstall them.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev

# The built frontend (frontend/dist, made by `make web`), when there is one.
# The globs keep this COPY valid while frontend/ or its build does not exist.
# frontend-v3/dist (made by the same `make web`) goes on top: v3 at / and /app/*, v1 as v1.html.
COPY infra/Dockerfile fronten[d]/dis[t] /app/frontend/dist/
COPY infra/Dockerfile frontend-v[3]/dis[t] /app/frontend/dist/
RUN rm /app/frontend/dist/Dockerfile

# Runs as the host user (compose `user:`), so HOME must be writable by anyone.
# r5py keeps its jar and networks under $XDG_CACHE_HOME: the writable cache volume.
ENV DATA_DIR=/data \
    FRONTEND_DIST=/app/frontend/dist \
    HOME=/tmp \
    XDG_CACHE_HOME=/data/cache/xdg \
    PYTHONUNBUFFERED=1 \
    PATH="/app/backend/.venv/bin:$PATH"
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
