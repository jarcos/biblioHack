#!/usr/bin/env bash
# Bring up the docker-compose dev stack and verify each service.
# Writes to scripts/verify-stack.log.

set -u
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
LOG="$REPO_ROOT/scripts/verify-stack.log"
: > "$LOG"

BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'; RESET=$'\033[0m'

step() {
  printf '\n%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n' "$BLUE" "$RESET" | tee -a "$LOG"
  printf '%s▶ %s%s\n' "$BOLD" "$*" "$RESET" | tee -a "$LOG"
}

ok()   { printf '%s✓ %s%s\n' "$GREEN" "$*" "$RESET" | tee -a "$LOG"; }
fail() { printf '%s✗ %s%s\n' "$RED"   "$*" "$RESET" | tee -a "$LOG"; }

# ─── Ensure .env exists ───
step ".env"
if [[ ! -f .env ]]; then
  cp .env.example .env
  ok ".env created from .env.example"
else
  ok ".env already exists"
fi

# ─── Build & start ───
step "docker compose up -d --build"
docker compose up -d --build 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
if [[ $rc -ne 0 ]]; then
  fail "compose failed (exit $rc)"; exit 1
fi
ok "compose started"

# ─── Wait for healthchecks ───
step "Waiting for healthchecks"
for svc in postgres redis api; do
  printf '  • %s ' "$svc" | tee -a "$LOG"
  for i in $(seq 1 60); do
    state=$(docker inspect --format '{{.State.Health.Status}}' "bibliohack-$svc" 2>/dev/null || echo "no-healthcheck")
    if [[ "$state" == "healthy" ]]; then
      printf '%s(healthy after %ds)%s\n' "$GREEN" "$((i*2))" "$RESET" | tee -a "$LOG"
      break
    fi
    if [[ $i -eq 60 ]]; then
      printf '%s(still %s after 120s)%s\n' "$RED" "$state" "$RESET" | tee -a "$LOG"
      docker compose logs --tail=30 "$svc" | tee -a "$LOG"
    fi
    sleep 2
  done
done

# Frontend has no healthcheck — just check it's running
printf '  • frontend ' | tee -a "$LOG"
if docker ps --filter "name=bibliohack-frontend" --filter "status=running" -q | grep -q .; then
  printf '%s(running)%s\n' "$GREEN" "$RESET" | tee -a "$LOG"
else
  printf '%s(not running)%s\n' "$RED" "$RESET" | tee -a "$LOG"
fi

# ─── docker compose ps ───
step "docker compose ps"
docker compose ps | tee -a "$LOG"

# ─── Hit API endpoints ───
step "Endpoint smoke tests"

curl_check() {
  local label="$1" url="$2" expect_status="$3"
  local actual
  actual=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url")
  if [[ "$actual" == "$expect_status" ]]; then
    ok "$label → $url → $actual"
  else
    fail "$label → $url → expected $expect_status, got $actual"
  fi
}

curl_check "API /healthz"       "http://localhost:8800/healthz"      "200"
curl_check "API /version"       "http://localhost:8800/version"      "200"
curl_check "API /openapi.json"  "http://localhost:8800/openapi.json" "200"
curl_check "API /docs"          "http://localhost:8800/docs"         "200"
curl_check "Frontend /"         "http://localhost:4321/"             "200"

# ─── Actually parse the health body ───
step "/healthz payload"
body=$(curl -s --max-time 5 http://localhost:8800/healthz)
echo "  $body" | tee -a "$LOG"
if echo "$body" | grep -q '"status":"ok"' && echo "$body" | grep -q '"version":"0.1.0"'; then
  ok "payload looks right"
else
  fail "unexpected payload"
fi

# ─── Postgres extensions ───
step "Postgres extensions"
docker compose exec -T postgres psql -U bibliohack -d bibliohack -c \
  "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector','pg_trgm','unaccent','btree_gin') ORDER BY extname;" 2>&1 | tee -a "$LOG"

step "Spanish FTS configuration"
docker compose exec -T postgres psql -U bibliohack -d bibliohack -c \
  "SELECT cfgname FROM pg_ts_config WHERE cfgname='spanish_unaccent';" 2>&1 | tee -a "$LOG"

step "Redis ping"
docker compose exec -T redis redis-cli ping 2>&1 | tee -a "$LOG"

step "DONE"
ok "Stack is up. Visit http://localhost:4321 and http://localhost:8800/docs"
