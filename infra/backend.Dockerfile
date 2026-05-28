# biblioHack — backend container
# Multi-stage build: heavy deps in builder, slim runtime image.

# ───── Builder ─────
FROM python:3.12-slim-bookworm AS builder

# Install uv (Astral) — single static binary.
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv

WORKDIR /app

# Cache deps separately from source.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# pyproject.toml + README.md (referenced by `readme = "README.md"`) + lockfile
# go in the cached layer; src is added on top so source edits don't bust deps.
COPY backend/pyproject.toml backend/README.md backend/uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev || \
    uv sync --no-install-project --no-dev

COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev || uv sync --no-dev

# ───── Runtime ─────
FROM python:3.12-slim-bookworm AS runtime

# Non-root user
RUN useradd --create-home --shell /bin/bash --uid 1000 bibliohack

WORKDIR /app

# Bring over the virtualenv built in the builder stage.
COPY --from=builder --chown=bibliohack:bibliohack /app/.venv /app/.venv
COPY --from=builder --chown=bibliohack:bibliohack /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER bibliohack

EXPOSE 8000

# Healthcheck targets the lightweight /healthz endpoint.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status == 200 else 1)" \
        || exit 1

CMD ["uvicorn", "bibliohack.interfaces.http.app:app", "--host", "0.0.0.0", "--port", "8000"]
