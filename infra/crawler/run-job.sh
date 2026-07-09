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

JOB="${1:?usage: run-job.sh discover_worker|refresh|covers|embed|relevance|canon_seed|canon_resolve|shelf_resolve|backlist}"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# ── Hard per-command timeout ──────────────────────────────────────
# A job that outlives its own schedule period is wedged, not slow. Twice
# (2026-07-03, 2026-07-08) a Page.goto timeout left the patchright driver
# hung: the job never exited, supercronic never restarted it ("job is still
# running"), and — because discover_worker holds the shared crawl flock —
# the WHOLE crawl plane froze until a manual container restart, days later.
# `run BUDGET CMD...` bounds one command: SIGTERM at BUDGET seconds, SIGKILL
# 120s later if ignored (a wedged driver ignores TERM). On timeout, leftover
# browser processes are killed too — only OPAC jobs use the browser and the
# shared flock makes them strictly serial, so nothing else's browser can be
# hit. Budgets are sized ~2× a healthy worst case and env-overridable from
# docker-compose.crawler.yml: bounding a wedge to minutes is the goal, a
# healthy run must never get close. `set -e` makes a timed-out command abort
# the job, so a wedge can't leave later commands running against dirty state.
run() {
  local budget="$1" rc=0
  shift
  timeout --kill-after=120 "$budget" "$@" || rc=$?
  if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
    echo "[$(ts)] $JOB TIMED OUT after ${budget}s (rc=$rc) — killing leftover browser processes"
    pkill -9 -f 'patchright|chromium|chrome' 2>/dev/null || true
  fi
  return "$rc"
}

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
if [ "$JOB" = "discover_worker" ]; then
  # The hourly growth job is the throughput engine — skipping it because a
  # 6-hourly job briefly held the lock costs a full hour of crawl capacity
  # (observed 2026-07-02: the 12:40 shelf_resolve held the lock through 13:00
  # and the whole 13:00-14:00 hour was lost). So it WAITS, bounded to stay
  # clear of its own next tick; supercronic won't start a second instance of
  # the same job meanwhile, so waiters never pile up.
  if ! flock -w "${LOCK_WAIT_SECONDS:-3300}" 9; then
    echo "[$(ts)] $JOB skipped — crawl lock still held after ${LOCK_WAIT_SECONDS:-3300}s"
    exit 0
  fi
elif ! flock -n 9; then
  # Everything else keeps skip-if-busy: those jobs re-fire soon enough, and
  # letting them queue behind the (long) hourly growth run would starve it.
  echo "[$(ts)] $JOB skipped — another crawl job is still running"
  exit 0
fi

echo "[$(ts)] $JOB START"
case "$JOB" in
  discover_worker)
    # Discovery pages ~40 result pages → minutes when healthy.
    run "${DISCOVER_TIMEOUT:-900}" bibliohack catalog discover \
      --year-from "${DISCOVER_YEAR_FROM:-2024}" \
      --max-results "${DISCOVER_MAX:-200}" \
      --rate "${CRAWL_RATE:-1.0}"
    # WORKER_MAX=2000 at ~1 req/s runs close to an hour when healthy — give
    # it 100 min; supercronic skipping one tick behind a long run is normal.
    run "${WORKER_TIMEOUT:-6000}" bibliohack catalog worker \
      --max-tasks "${WORKER_MAX:-200}" \
      --rate "${CRAWL_RATE:-1.0}"
    ;;
  refresh)
    run "${REFRESH_TIMEOUT:-3000}" bibliohack catalog refresh \
      --max-tasks "${REFRESH_MAX:-300}" \
      --rate "${CRAWL_RATE:-1.0}"
    ;;
  covers)
    # Off-OPAC: resolves cover images for catalogue ISBNs into the shared store.
    run "${COVERS_TIMEOUT:-1800}" bibliohack covers resolve --limit "${COVERS_MAX:-100}"
    ;;
  embed)
    # Off-OPAC: embeds records lacking a vector via the HF Inference API.
    run "${EMBED_TIMEOUT:-1800}" bibliohack catalog embed --limit "${EMBED_MAX:-200}"
    ;;
  relevance)
    # Off-OPAC, pure DB: rescores the whole catalogue from the availability
    # series + holdings so /browse and search lead with the best titles.
    run "${RELEVANCE_TIMEOUT:-1800}" bibliohack catalog relevance recompute --window-days "${RELEVANCE_WINDOW_DAYS:-90}"
    ;;
  canon_seed)
    # Off-OPAC (own lock): rebuild the canon seed from Wikidata + the curated
    # award fallback, then link seed works to records the mirror already holds.
    # Idempotent (upsert by source identity) — safe to re-run. Touches the OPAC
    # zero times, so it can run alongside the hourly growth crawl.
    run "${CANON_SEED_TIMEOUT:-1800}" bibliohack catalog canon refresh-seed \
      --min-sitelinks "${CANON_MIN_SITELINKS:-8}"
    run "${CANON_SEED_TIMEOUT:-1800}" bibliohack catalog canon refresh-awards
    run "${CANON_SEED_TIMEOUT:-1800}" bibliohack catalog canon match
    ;;
  canon_resolve)
    # On-OPAC (shared crawl lock — same polite budget as discover/refresh):
    # first link anything the worker has ingested since last run (DB-only),
    # then ask the OPAC whether the RBPA holds the still-unmatched classics and
    # seed the held TITNs into scrape_tasks for the worker to ingest. Bounded by
    # CANON_RESOLVE_MAX and rate-capped at CRAWL_RATE so it never starves the
    # hourly novedades growth or raises the OPAC request rate.
    run "${CANON_RESOLVE_TIMEOUT:-1800}" bibliohack catalog canon match
    run "${CANON_RESOLVE_TIMEOUT:-1800}" bibliohack catalog canon resolve \
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
    run "${SHELF_RESOLVE_TIMEOUT:-1800}" bibliohack shelf rematch
    run "${SHELF_RESOLVE_TIMEOUT:-1800}" bibliohack shelf resolve \
      --max "${SHELF_RESOLVE_MAX:-100}" \
      --rate "${CRAWL_RATE:-1.0}"
    ;;
  backlist)
    # M7 (docs/design/m7-backlist-crawl.md): top up the pre-2024 TITN backlog.
    # DB-only seeding (idempotent) at a lower priority than novedades, so the
    # hourly discover_worker drains fresh records first and fills idle capacity
    # with the backlist. Shares the crawl lock (default below) because the FIRST
    # run probes the OPAC for the high-water mark; after that it's pure DB.
    # Top-up mode: seeds only enough to refill the queue to BACKLIST_TARGET_DEPTH.
    run "${BACKLIST_TIMEOUT:-3000}" bibliohack catalog backlist \
      --target-depth "${BACKLIST_TARGET_DEPTH:-100000}" \
      --chunk "${BACKLIST_CHUNK:-50000}" \
      --rate "${CRAWL_RATE:-1.0}"
    ;;
  *)
    echo "[$(ts)] unknown job: $JOB" >&2
    exit 2
    ;;
esac
echo "[$(ts)] $JOB DONE"
