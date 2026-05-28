#!/usr/bin/env bash
# Verify the M0 scaffold end-to-end. Designed to be re-runnable.
#
# Usage:  bash scripts/verify-m0.sh
# Output: writes a log to scripts/verify-m0.log AND streams to stdout.

set -u
shopt -s nullglob

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

LOG_FILE="$REPO_ROOT/scripts/verify-m0.log"
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
  printf '%s▶ %s%s\n'                                                                  "$BOLD" "$*" "$RESET" | tee -a "$LOG_FILE"
  printf '%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n'   "$BLUE" "$RESET" | tee -a "$LOG_FILE"
}

run() {
  local label="$1"; shift
  printf '\n%s• %s%s\n' "$YELLOW" "$label" "$RESET" | tee -a "$LOG_FILE"
  printf '  $ %s\n' "$*" | tee -a "$LOG_FILE"
  # Use PIPESTATUS to capture the actual command's exit code, not tee's.
  # shellcheck disable=SC2068
  $@ 2>&1 | tee -a "$LOG_FILE"
  local rc=${PIPESTATUS[0]}
  if [[ $rc -eq 0 ]]; then
    printf '%s  ✓ ok%s\n' "$GREEN" "$RESET" | tee -a "$LOG_FILE"
    pass=$((pass + 1))
  else
    printf '%s  ✗ failed (exit %d)%s\n' "$RED" "$rc" "$RESET" | tee -a "$LOG_FILE"
    failures=$((failures + 1))
  fi
}

# ─────────────────────────────────────────────────────────────────
step "Toolchain — versions"
# ─────────────────────────────────────────────────────────────────
run "uv"       uv --version
run "python"   python3 --version
run "pnpm"     pnpm --version
run "node"     node --version
run "docker"   docker --version
run "git"      git --version

# ─────────────────────────────────────────────────────────────────
step "Backend — install & checks"
# ─────────────────────────────────────────────────────────────────
cd "$REPO_ROOT/backend"
run "uv sync"            uv sync --all-extras
run "ruff check"         uv run ruff check .
run "ruff format"        uv run ruff format --check .
run "mypy"               uv run mypy src
run "pytest"             uv run pytest -q

# ─────────────────────────────────────────────────────────────────
step "Frontend — install & checks"
# ─────────────────────────────────────────────────────────────────
cd "$REPO_ROOT/frontend"
run "pnpm install"       pnpm install
run "prettier"           pnpm format:check
run "eslint"             pnpm lint
run "typecheck"          pnpm typecheck
run "vitest"             pnpm test

# ─────────────────────────────────────────────────────────────────
step "Summary"
# ─────────────────────────────────────────────────────────────────
cd "$REPO_ROOT"
total=$((pass + failures))
if [[ $failures -eq 0 ]]; then
  printf '\n%s%s✅ All %d checks passed.%s\n' "$BOLD" "$GREEN" "$total" "$RESET" | tee -a "$LOG_FILE"
  exit 0
else
  printf '\n%s%s❌ %d/%d checks failed.%s See %s for details.\n' "$BOLD" "$RED" "$failures" "$total" "$RESET" "$LOG_FILE" | tee -a "$LOG_FILE"
  exit 1
fi
