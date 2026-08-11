#!/usr/bin/env bash
set -euo pipefail

if ((EUID == 0)); then
  runtime_dir=/run
else
  runtime_dir=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
  [[ -d $runtime_dir && -w $runtime_dir ]] || runtime_dir=/tmp
fi
report=$(mktemp "${runtime_dir%/}/ai-node-stack-health.XXXXXX")
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
