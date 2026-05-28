#!/usr/bin/env bash
# Quick diagnostic dump. Writes scripts/diag.log.
LOG="$(dirname "$0")/diag.log"
: > "$LOG"
{
  echo "=== docker ps ==="
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
  echo
  echo "=== lsof :8000 ==="
  lsof -nP -i :8000 || echo "(nothing)"
  echo
  echo "=== lsof :4321 ==="
  lsof -nP -i :4321 || echo "(nothing)"
  echo
  echo "=== lsof :5432 ==="
  lsof -nP -i :5432 | head -10 || echo "(nothing)"
} >> "$LOG" 2>&1
echo "wrote $LOG"
