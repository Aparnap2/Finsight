# syntax=docker/dockerfile:1
# Multi-stage build for FinSight API (FastAPI + NiceGUI)
#
# Targets:
#   runtime (default) — production image, no dev tooling
#   test              — runtime code + dev tooling (pytest), used only by
#                       docker-compose.test.yml (`target: test`)
#
# The default target must stay `runtime`: `docker build .` is what deployments
# and the operator demo use. A test stage placed last would silently ship
# pytest to production.

# ── Stage 1: Build dependencies ──────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/tmp/uv-cache

# Install uv (fast Python package installer)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first for layer caching
COPY pyproject.toml uv.lock ./

# Install production + compute dependencies
RUN uv sync --extra compute --no-dev --frozen

# ── Stage 2: Test image (dev tooling; never the default target) ──────────
# Same code as the runtime stage, plus the dev dependency group (pytest).
# Declared before the runtime stage so `docker build .` keeps producing the
# runtime image.
FROM builder AS test

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN uv sync --extra compute --frozen

# Mirrors the runtime stage COPY block below; keep them in sync.
COPY python_runtime/ ./python_runtime/
COPY apps/ ./apps/
COPY agents/ ./agents/
COPY finance/ ./finance/
COPY finplatform/ ./finplatform/
COPY shared/ ./shared/
COPY database/ ./database/
COPY tests/fixtures/reconciliation/triangle/ ./tests/fixtures/reconciliation/triangle/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY pyproject.toml ./

# ── Stage 3: Runtime image (default target) ─────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code (every importable package the runtime needs)
COPY python_runtime/ ./python_runtime/
COPY apps/ ./apps/
COPY agents/ ./agents/
COPY finance/ ./finance/
COPY finplatform/ ./finplatform/
COPY shared/ ./shared/
# SQL migration chain (alembic revisions live in alembic/). Needed by anyone
# running the documented fresh-DB sequence inside a container. Without it the
# integration suites discover zero SQL migrations and silently run against a
# schema with RLS disabled.
COPY database/ ./database/
# Operator demo fixture only. The rest of tests/ is never packaged into the
# runtime image; test runs mount it read-only (see docker-compose.test.yml).
# Without this, `python -m finance.reconciliation.operator_report` exits 2
# inside the container with "default cases fixture is missing".
COPY tests/fixtures/reconciliation/triangle/ ./tests/fixtures/reconciliation/triangle/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY pyproject.toml ./

# Run as a non-root user (Slice 3: least privilege in managed runtime)
RUN useradd --create-home --uid 10001 finsight \
    && chown -R finsight:finsight /app
USER finsight

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# Default command: start the API server
CMD ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
