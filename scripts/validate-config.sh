#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
strict=false
[[ ${1:-} == --strict ]] && strict=true

failures=0
fail() { echo "FAIL $*" >&2; failures=$((failures + 1)); }
ok() { echo "OK   $*"; }

for script in "$repo_root"/scripts/*.sh "$repo_root"/agent-platform/scripts/agentctl; do
  if bash -n "$script"; then ok "bash syntax: ${script#"$repo_root"/}"; else fail "bash syntax: ${script#"$repo_root"/}"; fi
done

if command -v shellcheck >/dev/null; then
  if shellcheck "$repo_root"/scripts/*.sh "$repo_root"/agent-platform/scripts/agentctl; then
    ok "ShellCheck static analysis"
  else
    fail "ShellCheck static analysis"
  fi
else
  echo "SKIP ShellCheck static analysis (shellcheck is not installed)"
fi

if python3 -m py_compile \
  "$repo_root/services/agent-gateway/app.py" \
  "$repo_root/services/embedding/app.py" \
  "$repo_root/services/nvidia-exporter/exporter.py"; then
  ok "Python syntax"
else
  fail "Python syntax"
fi

if jq -e . "$repo_root/monitoring/grafana/dashboards/ai-node-overview.json" >/dev/null; then
  ok "Grafana dashboard JSON"
else
  fail "Grafana dashboard JSON"
fi

compose=(docker compose --env-file "$repo_root/.env" -f "$repo_root/compose/ai-node.yml")
if $strict; then
  for required in agent-gateway.env grafana.env speedtest.env; do
    [[ -s "$repo_root/secrets/$required" ]] || fail "required secret file missing or empty: secrets/$required"
  done
  gateway_key=$(sed -n 's/^AGENT_GATEWAY_KEY=//p' "$repo_root/secrets/agent-gateway.env" 2>/dev/null | tail -n1)
  [[ ${#gateway_key} -ge 32 ]] || fail "AGENT_GATEWAY_KEY must contain at least 32 characters"
  if "${compose[@]}" config --quiet; then ok "Docker Compose configuration"; else fail "Docker Compose configuration"; fi
else
  if "${compose[@]}" -f "$repo_root/compose/validation.yml" config --quiet; then
    ok "Docker Compose configuration (validation secrets)"
  else
    fail "Docker Compose configuration"
  fi
fi

prometheus_image=$("${compose[@]}" -f "$repo_root/compose/validation.yml" config --images 2>/dev/null | awk '/prom\/prometheus/ {print; exit}')
if [[ -n $prometheus_image ]] && docker image inspect "$prometheus_image" >/dev/null 2>&1; then
  if docker run --rm --entrypoint /bin/promtool \
    -v "$repo_root/monitoring:/etc/prometheus:ro" "$prometheus_image" \
    check config /etc/prometheus/prometheus.yml >/dev/null; then
    ok "Prometheus configuration and alert rules"
  else
    fail "Prometheus configuration or alert rules"
  fi
else
  echo "SKIP Prometheus validation (image is not present locally)"
fi

((failures == 0)) || { echo "Validation failures: $failures" >&2; exit 1; }
echo "Validation passed"
