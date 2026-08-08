#!/usr/bin/env bash
set -uo pipefail

source /srv/ai-node/.env
base="http://${LAN_IP}"

failures=0
check_url() {
  local name=$1 url=$2
  if curl -fsS --max-time 15 -o /dev/null "$url"; then
    printf 'OK   %-22s %s\n' "$name" "$url"
  else
    printf 'FAIL %-22s %s\n' "$name" "$url"
    failures=$((failures + 1))
  fi
}

if docker info >/dev/null 2>&1; then
  echo "OK   Docker daemon"
else
  echo "FAIL Docker daemon"
  failures=$((failures + 1))
fi

if nvidia-smi >/dev/null 2>&1; then
  echo "OK   NVIDIA host GPU"
else
  echo "FAIL NVIDIA host GPU"
  failures=$((failures + 1))
fi

check_url "Ollama API" "${base}:11434/api/tags"
check_url "Open WebUI" "${base}:3000/health"
check_url "Embeddings" "${base}:8081/health"
check_url "ComfyUI" "${base}:8188/system_stats"
check_url "Prometheus" "${base}:9091/-/healthy"
check_url "Grafana" "${base}:3001/api/health"
check_url "Uptime Kuma" "${base}:3002/"
check_url "Speedtest Tracker" "${base}:8765/"

down_targets=$(curl -fsS --max-time 15 "${base}:9091/api/v1/targets?state=active" 2>/dev/null | jq '[.data.activeTargets[] | select(.health != "up")] | length' 2>/dev/null || echo unknown)
if [[ $down_targets == 0 ]]; then
  echo "OK   Prometheus targets healthy"
else
  echo "FAIL Prometheus unhealthy targets: $down_targets"
  failures=$((failures + 1))
fi

if tailscale status --json 2>/dev/null | jq -e '.BackendState == "Running"' >/dev/null; then
  echo "OK   Tailscale connected"
else
  echo "FAIL Tailscale disconnected"
  failures=$((failures + 1))
fi

echo "Health check failures: $failures"
exit "$failures"
