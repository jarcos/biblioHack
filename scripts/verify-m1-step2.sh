#!/usr/bin/env bash
# Verify M1 step 2 (domain model + migration).
# Writes to scripts/verify-m1-step2.log.

set -u
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
LOG="$REPO_ROOT/scripts/verify-m1-step2.log"
: > "$LOG"

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'; BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; RESET=$'\033[0m'

step() {
  printf '\n%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n' "$BLUE" "$RESET" | tee -a "$LOG"
  printf '%s▶ %s%s\n' "$BOLD" "$*" "$RESET" | tee -a "$LOG"
}

run() {
  local label="$1"; shift
  printf '\n%s• %s%s\n' "$YELLOW" "$label" "$RESET" | tee -a "$LOG"
  # shellcheck disable=SC2068
  $@ 2>&1 | tee -a "$LOG"
  local rc=${PIPESTATUS[0]}
  if [[ $rc -eq 0 ]]; then
    printf '%s  ✓ ok%s\n' "$GREEN" "$RESET" | tee -a "$LOG"
  else
    printf '%s  ✗ failed (exit %d)%s\n' "$RED" "$rc" "$RESET" | tee -a "$LOG"
    exit $rc
  fi
}

# ─── Backend code quality ───
step "Lint / format / typecheck"
cd "$REPO_ROOT/backend"
run "ruff check"       uv run ruff check .
run "ruff format"      uv run ruff format --check .
run "mypy"             uv run mypy src

# ─── Backend tests ───
step "Pytest (full suite)"
run "pytest"           uv run pytest -q

# ─── Apply the migration to the running Postgres ───
step "Alembic upgrade"
# Point alembic at the host-published port (8800/postgres maps to 5432).
export DATABASE_URL="postgresql+asyncpg://bibliohack:bibliohack@localhost:5432/bibliohack"
export DATABASE_URL_SYNC="postgresql+psycopg://bibliohack:bibliohack@localhost:5432/bibliohack"
run "alembic upgrade head"   uv run alembic upgrade head
run "alembic current"        uv run alembic current

# ─── Verify schema is in place ───
step "Verify tables exist"
cd "$REPO_ROOT"
TABLES=$(docker compose exec -T postgres psql -U bibliohack -d bibliohack -tA -c \
  "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT LIKE 'pg_%' ORDER BY tablename;")
echo "$TABLES" | tee -a "$LOG"
expected="alembic_version bibliographic_records branches contributors copies isbns scrape_log scrape_tasks subjects"
for t in $expected; do
  if echo "$TABLES" | grep -qx "$t"; then
    printf '%s  ✓ %s%s\n' "$GREEN" "$t" "$RESET" | tee -a "$LOG"
  else
    printf '%s  ✗ missing: %s%s\n' "$RED" "$t" "$RESET" | tee -a "$LOG"
    exit 1
  fi
done

step "Verify FTS column + indexes"
docker compose exec -T postgres psql -U bibliohack -d bibliohack -c \
  "SELECT indexname FROM pg_indexes WHERE tablename='bibliographic_records' ORDER BY indexname;" | tee -a "$LOG"

step "Done"
printf '%s%s✅ M1 step 2 verified.%s\n' "$BOLD" "$GREEN" "$RESET" | tee -a "$LOG"
