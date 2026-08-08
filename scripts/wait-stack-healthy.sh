#!/usr/bin/env bash
set -euo pipefail

report="/run/ai-node-stack-health.$$"
trap 'rm -f -- "$report"' EXIT

for _ in $(seq 1 60); do
  if /srv/ai-node/scripts/health-check.sh >"$report" 2>&1; then
    cat "$report"
    exit 0
  fi
  sleep 5
done

cat "$report" >&2
echo "AI node stack did not become healthy within 300 seconds" >&2
exit 1

