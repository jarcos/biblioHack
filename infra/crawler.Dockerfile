# biblioHack — autonomous crawler container (the NAS compute plane).
#
# Runs the Scrapling/Camoufox OPAC crawler on a schedule via supercronic:
#   nightly  discover + worker   → catalogue growth (novedades)
#   hourly   refresh             → fresh availability snapshots
#
# Deliberately NOT part of docker-compose.prod.yml: the api/frontend CD must
# never be blocked by this heavy (Firefox) image build. Brought up once with
# `docker compose -f docker-compose.crawler.yml up -d --build`; restart
# policy keeps it alive across NAS reboots. See ARCHITECTURE.md §10.
#
# Build (on the NAS, from /volume1/docker/bibliohack):
#   docker compose -f docker-compose.crawler.yml build   # uses network: host

# ───── Builder: deps incl. the [scraper] + [covers] extras ─────
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY backend/pyproject.toml backend/README.md backend/uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --extra scraper --extra covers || \
    uv sync --no-install-project --no-dev --extra scraper --extra covers

COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra scraper --extra covers || \
    uv sync --no-dev --extra scraper --extra covers

# ───── Runtime ─────
FROM python:3.12-slim-bookworm AS runtime

RUN useradd --create-home --shell /bin/bash --uid 1000 bibliohack
WORKDIR /app

COPY --from=builder --chown=bibliohack:bibliohack /app/.venv /app/.venv
COPY --from=builder --chown=bibliohack:bibliohack /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Browser OS libraries for BOTH engines — Scrapling's StealthyFetcher drives
# Patchright Chromium (despite the "Camoufox" naming), so Chromium's libs
# (libnss3, libgbm, …) are required too. `playwright install-deps` (no engine
# arg) pulls the full set reliably on bookworm. Plus fonts + supercronic.
# `releases/latest/download` always resolves to the newest asset (no pinned
# tag to rot). flock (util-linux) guards against overlapping crawl runs.
RUN playwright install-deps \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        fonts-liberation fonts-unifont ca-certificates curl util-linux \
 && curl -fsSL -o /usr/local/bin/supercronic \
        https://github.com/aptible/supercronic/releases/latest/download/supercronic-linux-amd64 \
 && chmod +x /usr/local/bin/supercronic \
 && apt-get purge -y curl \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Bake both browser engines into the image: Patchright Chromium (the one
# StealthyFetcher actually launches → ~/.cache/ms-playwright) and Camoufox
# (~/.cache/camoufox) to match the Makefile's scraper-install-browsers.
# Done BEFORE copying the schedule files so edits to the crontab / job wrapper
# don't bust these expensive (~hundreds-of-MB) download layers.
USER bibliohack
RUN patchright install chromium && camoufox fetch
USER root

COPY infra/crawler/crontab /app/crontab
COPY infra/crawler/run-job.sh /app/run-job.sh
RUN chmod +x /app/run-job.sh && chown -R bibliohack:bibliohack /app

USER bibliohack

# supercronic interprets the crontab and runs jobs on schedule, logging to
# stdout (visible via `docker logs bibliohack-crawler`).
CMD ["supercronic", "/app/crontab"]
