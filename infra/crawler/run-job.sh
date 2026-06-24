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

JOB="${1:?usage: run-job.sh discover_worker|refresh|covers|embed|relevance|canon_seed|canon_resolve|shelf_resolve}"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# OPAC jobs share one lock (one polite OPAC budget). Cover resolution hits
# Open Library / Google Books, not the OPAC, so it gets its own lock and can
# run alongside an OPAC crawl.
case "$JOB" in
  covers) LOCK="/tmp/bibliohack-covers.lock" ;;
  embed) LOCK="/tmp/bibliohack-embed.lock" ;;
  relevance) LOCK="/tmp/bibliohack-relevance.lock" ;;
  # canon_seed is off-OPAC (WDQS / curated list / DB-only match), so it gets its
  # own lock and can run alongside an OPAC crawl. canon_resolve DOES hit the
  # OPAC, so it deliberately falls through to the shared crawl lock below.
  canon_seed) LOCK="/tmp/bibliohack-canon-seed.lock" ;;
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
  embed)
    # Off-OPAC: embeds records lacking a vector via the HF Inference API.
    bibliohack catalog embed --limit "${EMBED_MAX:-200}"
    ;;
  relevance)
    # Off-OPAC, pure DB: rescores the whole catalogue from the availability
    # series + holdings so /browse and search lead with the best titles.
    bibliohack catalog relevance recompute --window-days "${RELEVANCE_WINDOW_DAYS:-90}"
    ;;
  canon_seed)
    # Off-OPAC (own lock): rebuild the canon seed from Wikidata + the curated
    # award fallback, then link seed works to records the mirror already holds.
    # Idempotent (upsert by source identity) — safe to re-run. Touches the OPAC
    # zero times, so it can run alongside the hourly growth crawl.
    bibliohack catalog canon refresh-seed \
      --min-sitelinks "${CANON_MIN_SITELINKS:-8}"
    bibliohack catalog canon refresh-awards
    bibliohack catalog canon match
    ;;
  canon_resolve)
    # On-OPAC (shared crawl lock — same polite budget as discover/refresh):
    # first link anything the worker has ingested since last run (DB-only),
    # then ask the OPAC whether the RBPA holds the still-unmatched classics and
    # seed the held TITNs into scrape_tasks for the worker to ingest. Bounded by
    # CANON_RESOLVE_MAX and rate-capped at CRAWL_RATE so it never starves the
    # hourly novedades growth or raises the OPAC request rate.
    bibliohack catalog canon match
    bibliohack catalog canon resolve \
      --max "${CANON_RESOLVE_MAX:-150}" \
      --rate "${CRAWL_RATE:-1.0}"
    ;;
  shelf_resolve)
    # On-OPAC (shared crawl lock — same polite budget as discover/refresh): the
    # demand-driven fetcher for user shelves. First link any unmatched shelf
    # entries whose record the worker has ingested since last run (DB-only), then
    # ask the OPAC whether the RBPA holds the still-unmatched books (deduped across
    # users) and seed the held TITNs into scrape_tasks for the worker. Bounded by
    # SHELF_RESOLVE_MAX and rate-capped at CRAWL_RATE so it never starves the
    # hourly novedades growth or raises the OPAC request rate.
    bibliohack shelf rematch
    bibliohack shelf resolve \
      --max "${SHELF_RESOLVE_MAX:-100}" \
      --rate "${CRAWL_RATE:-1.0}"
    ;;
  *)
    echo "[$(ts)] unknown job: $JOB" >&2
    exit 2
    ;;
esac
echo "[$(ts)] $JOB DONE"
