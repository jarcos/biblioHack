#!/usr/bin/env bash
# Wrapper for the two scheduled crawl jobs.
#
# A single shared flock prevents overlap: a long nightly discover+worker must
# not collide with the next hourly refresh (they share one polite OPAC budget).
# All bounds are env-overridable from docker-compose.crawler.yml. Everything
# logs to stdout so `docker logs bibliohack-crawler` is the single source.
set -euo pipefail

# supercronic execs jobs with the container env, but make the venv explicit so
# `bibliohack` resolves regardless of how the scheduler sets PATH.
export PATH="/app/.venv/bin:${PATH:-/usr/local/bin:/usr/bin:/bin}"

JOB="${1:?usage: run-job.sh discover_worker|refresh|covers}"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# OPAC jobs share one lock (one polite OPAC budget). Cover resolution hits
# Open Library / Google Books, not the OPAC, so it gets its own lock and can
# run alongside an OPAC crawl.
case "$JOB" in
  covers) LOCK="/tmp/bibliohack-covers.lock" ;;
  *) LOCK="/tmp/bibliohack-crawl.lock" ;;
esac
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(ts)] $JOB skipped — another crawl job is still running"
  exit 0
fi

echo "[$(ts)] $JOB START"
case "$JOB" in
  discover_worker)
    bibliohack catalog discover \
      --year-from "${DISCOVER_YEAR_FROM:-2024}" \
      --max-results "${DISCOVER_MAX:-200}" \
      --rate "${CRAWL_RATE:-1.0}"
    bibliohack catalog worker \
      --max-tasks "${WORKER_MAX:-200}" \
      --rate "${CRAWL_RATE:-1.0}"
    ;;
  refresh)
    bibliohack catalog refresh \
      --max-tasks "${REFRESH_MAX:-300}" \
      --rate "${CRAWL_RATE:-1.0}"
    ;;
  covers)
    # Off-OPAC: resolves cover images for catalogue ISBNs into the shared store.
    bibliohack covers resolve --limit "${COVERS_MAX:-100}"
    ;;
  *)
    echo "[$(ts)] unknown job: $JOB" >&2
    exit 2
    ;;
esac
echo "[$(ts)] $JOB DONE"
