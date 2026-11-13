# Rețeaua Vie backend image: FastAPI on :3000, plus the system tools the
# pipeline needs (Java 21 for r5py and the GTFS-RT validator, osmium for OSM,
# Pango/HarfBuzz and Noto fonts for the WeasyPrint poster).
# Build from the repo root: docker build -f infra/Dockerfile .
# Data and secrets are never baked in: DATA_DIR is a volume, the env file comes
# from compose (env_file).
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3.12 ca-certificates curl unzip tzdata \
      openjdk-21-jre-headless osmium-tool \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-noto-core \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV UV_PYTHON=python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app/backend
# Dependencies first, so a code change does not reinstall them.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-install-project
COPY backend/ ./
RUN uv sync --frozen

ENV DATA_DIR=/data \
    PATH="/app/backend/.venv/bin:$PATH"
EXPOSE 3000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
