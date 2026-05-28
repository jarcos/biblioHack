#!/usr/bin/env bash
# Verify the FTS-authors migration end-to-end:
#   1. ruff (lint)
#   2. ruff format --check
#   3. mypy
#   4. catalog HTTP integration tests (testcontainers Postgres + Alembic upgrade)
#   5. full backend test suite (coverage threshold included)
#
# Designed to be re-runnable. Writes a log alongside the script.

set -u
shopt -s nullglob

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

LOG_FILE="$REPO_ROOT/scripts/verify-fts-authors.log"
: > "$LOG_FILE"

failures=0
pass=0

GREEN=$'\033[0;32m'
RED=$'\033[0;31m'
YELLOW=$'\033[0;33m'
BLUE=$'\033[0;34m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

step() {
  printf '\n%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n' "$BLUE" "$RESET" | tee -a "$LOG_FILE"
  printf '%s▶ %s%s\n' "$BOLD" "$*" "$RESET" | tee -a "$LOG_FILE"
  printf '%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n' "$BLUE" "$RESET" | tee -a "$LOG_FILE"
}

run() {
  local label="$1"; shift
  printf '\n%s• %s%s\n' "$YELLOW" "$label" "$RESET" | tee -a "$LOG_FILE"
  printf '  $ %s\n' "$*" | tee -a "$LOG_FILE"
  "$@" 2>&1 | tee -a "$LOG_FILE"
  local rc=${PIPESTATUS[0]}
  if [[ $rc -eq 0 ]]; then
    printf '%s  ✓ ok%s\n' "$GREEN" "$RESET" | tee -a "$LOG_FILE"
    pass=$((pass + 1))
  else
    printf '%s  ✗ failed (exit %d)%s\n' "$RED" "$rc" "$RESET" | tee -a "$LOG_FILE"
    failures=$((failures + 1))
  fi
}

step "Backend — static checks"
run "ruff check"       bash -c 'cd backend && uv run ruff check .'
run "ruff format"      bash -c 'cd backend && uv run ruff format --check .'
run "mypy"             bash -c 'cd backend && uv run mypy src'

step "Backend — catalog HTTP tests (focused)"
run "http tests"       bash -c 'cd backend && uv run pytest -q tests/catalog/test_catalog_http.py'

step "Backend — full test suite"
run "full pytest"      bash -c 'cd backend && uv run pytest -q'

printf '\n%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n' "$BLUE" "$RESET" | tee -a "$LOG_FILE"
if [[ $failures -eq 0 ]]; then
  printf '%s✔ all %d checks passed%s\n' "$GREEN" "$pass" "$RESET" | tee -a "$LOG_FILE"
  exit 0
else
  printf '%s✘ %d failure(s), %d passed — see %s%s\n' "$RED" "$failures" "$pass" "$LOG_FILE" "$RESET" | tee -a "$LOG_FILE"
  exit 1
fi
