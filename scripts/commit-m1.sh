#!/usr/bin/env bash
# Make the 5 atomic M1 commits. Each one is staged precisely and uses a
# pre-written commit message file from scripts/commit-msgs/.
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

LOG="$REPO_ROOT/scripts/commit-m1.log"
: > "$LOG"

PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
export PATH

step() {
  printf '\n=== %s ===\n' "$*" | tee -a "$LOG"
}

# Sanity check: refuse to run if we're not on a fresh M0 baseline.
if [[ $(git rev-list --count HEAD) -ne 1 ]]; then
  echo "Refusing to run: expected exactly one commit (M0 scaffold) before this script."
  git log --oneline | tee -a "$LOG"
  exit 1
fi

# ---- Commit 1: catalog/holdings domain + Alembic ----
step "Commit 1: catalog/holdings domain + Alembic"
git add \
  ARCHITECTURE.md \
  backend/pyproject.toml \
  Makefile \
  backend/alembic.ini \
  backend/alembic/env.py \
  backend/alembic/script.py.mako \
  backend/alembic/versions/20260528_0000_m1_initial.py \
  backend/src/bibliohack/catalog/__init__.py \
  backend/src/bibliohack/catalog/domain/__init__.py \
  backend/src/bibliohack/catalog/domain/contributor.py \
  backend/src/bibliohack/catalog/domain/isbn.py \
  backend/src/bibliohack/catalog/domain/record.py \
  backend/src/bibliohack/catalog/infrastructure/postgres/__init__.py \
  backend/src/bibliohack/catalog/infrastructure/postgres/models.py \
  backend/src/bibliohack/holdings/domain/__init__.py \
  backend/src/bibliohack/holdings/domain/branch.py \
  backend/src/bibliohack/holdings/domain/copy.py \
  backend/src/bibliohack/holdings/infrastructure/__init__.py \
  backend/src/bibliohack/holdings/infrastructure/postgres/__init__.py \
  backend/src/bibliohack/holdings/infrastructure/postgres/models.py \
  backend/src/bibliohack/shared/domain/entity.py \
  backend/src/bibliohack/shared/infrastructure/db.py \
  backend/tests/catalog/test_contributor.py \
  backend/tests/catalog/test_isbn.py \
  backend/tests/catalog/test_record.py \
  backend/tests/holdings/__init__.py \
  backend/tests/holdings/test_branch.py \
  backend/tests/holdings/test_copy.py \
  scripts/verify-m1-step2.sh \
  scripts/inspect-db.sh
git commit -F scripts/commit-msgs/01-domain.txt 2>&1 | tee -a "$LOG"
git log --oneline -1 | tee -a "$LOG"

# ---- Commit 2: AbsysNET URL builder ----
step "Commit 2: AbsysNET URL builder"
git add \
  backend/src/bibliohack/catalog/domain/titn.py \
  backend/src/bibliohack/catalog/infrastructure/absysnet/urls.py \
  backend/tests/catalog/__init__.py \
  backend/tests/catalog/test_titn.py \
  backend/tests/catalog/test_absysnet_urls.py
git commit -F scripts/commit-msgs/02-urls.txt 2>&1 | tee -a "$LOG"
git log --oneline -1 | tee -a "$LOG"

# ---- Commit 3: OpacGateway port + Scrapling adapter ----
step "Commit 3: OpacGateway port + Scrapling adapter"
git add \
  backend/src/bibliohack/catalog/application/__init__.py \
  backend/src/bibliohack/catalog/application/ports.py \
  backend/src/bibliohack/catalog/infrastructure/absysnet/__init__.py \
  backend/src/bibliohack/catalog/infrastructure/absysnet/throttle.py \
  backend/src/bibliohack/catalog/infrastructure/absysnet/gateway.py \
  backend/tests/catalog/test_throttle.py \
  backend/tests/catalog/test_gateway.py
git commit -F scripts/commit-msgs/03-gateway.txt 2>&1 | tee -a "$LOG"
git log --oneline -1 | tee -a "$LOG"

# ---- Commit 4: AbsysNET HTML parser + fixture ----
step "Commit 4: AbsysNET HTML parser"
git add \
  backend/src/bibliohack/catalog/infrastructure/absysnet/parser.py \
  backend/tests/catalog/fixtures/titn_1.html \
  backend/tests/catalog/test_parser.py
git commit -F scripts/commit-msgs/04-parser.txt 2>&1 | tee -a "$LOG"
git log --oneline -1 | tee -a "$LOG"

# ---- Commit 5: TITN probe CLI (gap-tolerant) + housekeeping ----
step "Commit 5: TITN probe CLI + gap tolerance"
git add -A
git commit -F scripts/commit-msgs/05-probe.txt 2>&1 | tee -a "$LOG"
git log --oneline -1 | tee -a "$LOG"

# ---- Final state ----
step "Final state"
git log --oneline | tee -a "$LOG"
echo
echo "git status:"
git status --short | tee -a "$LOG"
