#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
strict=false
case ${1:-} in
  "") ;;
  --strict) strict=true ;;
  *) echo "Usage: $0 [--strict]" >&2; exit 2 ;;
esac
(($# <= 1)) || { echo "Usage: $0 [--strict]" >&2; exit 2; }

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
  "$repo_root/services/agent-gateway/test_app.py" \
  "$repo_root/services/embedding/app.py" \
  "$repo_root/services/embedding/test_app.py" \
  "$repo_root/services/nvidia-exporter/exporter.py" \
  "$repo_root/services/nvidia-exporter/test_exporter.py"; then
  ok "Python syntax"
else
  fail "Python syntax"
fi

if command -v jq >/dev/null; then
  if jq -e . \
    "$repo_root/monitoring/grafana/dashboards/ai-node-overview.json" \
    "$repo_root/services/playwright/package.json" \
    "$repo_root/services/playwright/package-lock.json" >/dev/null; then
    ok "JSON configuration"
  else
    fail "JSON configuration"
  fi
else
  echo "SKIP JSON configuration (jq is not installed)"
fi

if command -v node >/dev/null; then
  if node --check "$repo_root/services/playwright/test.js"; then ok "Playwright JavaScript syntax"; else fail "Playwright JavaScript syntax"; fi
else
  echo "SKIP Playwright JavaScript syntax (node is not installed)"
fi

# .env only exists on the server; fall back to .env.example so local
# validation works on a workstation clone.
env_file=$repo_root/.env
[[ -f $env_file ]] || env_file=$repo_root/.env.example
compose=(docker compose --env-file "$env_file" -f "$repo_root/compose/ai-node.yml")
compose_dev=(docker compose --profile dev --env-file "$env_file" -f "$repo_root/compose/ai-node.yml")
if $strict; then
  for required in agent-gateway.env grafana.env speedtest.env; do
    [[ -s "$repo_root/secrets/$required" ]] || fail "required secret file missing or empty: secrets/$required"
  done
  gateway_key=$(sed -n 's/^AGENT_GATEWAY_KEY=//p' "$repo_root/secrets/agent-gateway.env" 2>/dev/null | tail -n1)
  [[ ${#gateway_key} -ge 32 ]] || fail "AGENT_GATEWAY_KEY must contain at least 32 characters"
  if "${compose[@]}" config --quiet && "${compose_dev[@]}" config --quiet; then ok "Docker Compose configuration (default and dev profiles)"; else fail "Docker Compose configuration"; fi
else
  if "${compose[@]}" -f "$repo_root/compose/validation.yml" config --quiet \
    && "${compose_dev[@]}" -f "$repo_root/compose/validation.yml" config --quiet; then
    ok "Docker Compose configuration (default/dev profiles with validation secrets)"
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

gateway_image=$("${compose[@]}" -f "$repo_root/compose/validation.yml" config --format json 2>/dev/null | jq -r '.services["agent-gateway"].image')
if [[ -n $gateway_image ]] && docker image inspect "$gateway_image" >/dev/null 2>&1; then
  if docker run --rm --network none --user 1000:1000 --read-only --cap-drop ALL \
    --tmpfs /tmp:rw,noexec,nosuid,size=128m,uid=1000,gid=1000 \
    --tmpfs /srv/agent-workspaces:rw,nosuid,size=32m,uid=1000,gid=1000 \
    --tmpfs /srv/agent-artifacts:rw,nosuid,size=32m,uid=1000,gid=1000 \
    --tmpfs /srv/agent-cache:rw,nosuid,size=32m,uid=1000,gid=1000 \
    -e AGENT_GATEWAY_KEY=validation-only-key-000000000000000000000000 \
    --entrypoint python "$gateway_image" -m unittest -v test_app.py; then
    ok "Agent gateway regression tests"
  else
    fail "Agent gateway regression tests"
  fi
else
  echo "SKIP Agent gateway regression tests (image is not present locally)"
fi

embedding_image=$("${compose[@]}" -f "$repo_root/compose/validation.yml" config --format json 2>/dev/null | jq -r '.services.embeddings.image')
if [[ -n $embedding_image ]] && docker image inspect "$embedding_image" >/dev/null 2>&1; then
  if docker run --rm --network none --entrypoint python "$embedding_image" -m unittest -v test_app.py; then
    ok "Embedding API regression tests"
  else
    fail "Embedding API regression tests"
  fi
else
  echo "SKIP Embedding API regression tests (image is not present locally)"
fi

nvidia_image=$("${compose[@]}" -f "$repo_root/compose/validation.yml" config --format json 2>/dev/null | jq -r '.services["nvidia-exporter"].image')
if [[ -n $nvidia_image ]] && docker image inspect "$nvidia_image" >/dev/null 2>&1; then
  if docker run --rm --network none --read-only --cap-drop ALL --entrypoint python3 "$nvidia_image" -m unittest -v test_exporter.py; then
    ok "NVIDIA exporter regression tests"
  else
    fail "NVIDIA exporter regression tests"
  fi
else
  echo "SKIP NVIDIA exporter regression tests (image is not present locally)"
fi

((failures == 0)) || { echo "Validation failures: $failures" >&2; exit 1; }
echo "Validation passed"
