#!/usr/bin/env bash
# Quick DB inspection — prove the schema is what we expect. Writes
# scripts/inspect-db.log so Claude can read the output too.
set -u
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$REPO_ROOT/scripts/inspect-db.log"
: > "$LOG"

{
  echo "=== make db-current ==="
  cd "$REPO_ROOT" && make db-current 2>&1 | tail -5

  echo
  echo "=== docker compose exec postgres psql \\dt ==="
  docker compose exec -T postgres psql -U bibliohack -d bibliohack -c "\dt"

  echo
  echo "=== \d bibliographic_records ==="
  docker compose exec -T postgres psql -U bibliohack -d bibliohack -c "\d bibliographic_records"

  echo
  echo "=== \d scrape_tasks ==="
  docker compose exec -T postgres psql -U bibliohack -d bibliohack -c "\d scrape_tasks"

  echo
  echo "=== \d copies ==="
  docker compose exec -T postgres psql -U bibliohack -d bibliohack -c "\d copies"

  echo
  echo "=== Round-trip: downgrade then upgrade ==="
  cd "$REPO_ROOT" && make db-downgrade 2>&1 | tail -3
  echo "--- after downgrade ---"
  docker compose exec -T postgres psql -U bibliohack -d bibliohack -tA -c \
    "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename NOT LIKE 'pg_%';"
  cd "$REPO_ROOT" && make db-upgrade 2>&1 | tail -3
  echo "--- after re-upgrade ---"
  docker compose exec -T postgres psql -U bibliohack -d bibliohack -tA -c \
    "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename NOT LIKE 'pg_%';"
} | tee -a "$LOG"
