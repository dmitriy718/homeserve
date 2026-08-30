#!/usr/bin/env bash
# Cooperative GPU lease client for host-side and agent workloads.
# Talks to the gpu-scheduler container (compose/ai-node.yml), which is
# published on 127.0.0.1 only — never on LAN_IP/TAILSCALE_IP. This is
# voluntary coordination, not enforcement; see docs/GPU_SCHEDULING.md.
set -euo pipefail

API="${GPU_SCHEDULER_URL:-http://127.0.0.1:8077}"

usage() {
  cat >&2 <<'EOF'
Usage:
  gpu-lock.sh acquire <holder> <kind> [--wait] [--ttl SECONDS]
  gpu-lock.sh release <holder>
  gpu-lock.sh status
  gpu-lock.sh run <holder> <kind> [--ttl SECONDS] -- <cmd...>

<kind> is llm | image | other. Keep <holder> to [a-z0-9._-] — it goes into the
URL path. `run` acquires (waiting for the lease), heartbeats in the background
while <cmd...> runs, and releases on any exit.
EOF
  exit 2
}

need_jq() { command -v jq >/dev/null 2>&1 || { echo "gpu-lock.sh requires jq" >&2; exit 1; }; }

acquire() {
  local holder=$1 kind=$2 wait=$3 ttl=$4
  local payload target response code body
  payload=$(jq -nc --arg h "$holder" --arg k "$kind" --argjson t "$ttl" \
    '{holder: $h, kind: $k, ttl_seconds: $t}')
  while :; do
    target="$API/leases"
    $wait && target="$target?wait=true&wait_timeout=300"
    if ! response=$(curl -sS -X POST "$target" -H 'Content-Type: application/json' \
        -d "$payload" -w $'\n%{http_code}'); then
      echo "gpu-lock: scheduler unreachable at $API" >&2
      return 1
    fi
    code=${response##*$'\n'}
    body=${response%$'\n'*}
    if [[ $code == 200 ]]; then
      printf '%s\n' "$body"
      return 0
    fi
    if [[ $code == 409 ]] && $wait; then
      sleep 1  # long-poll timed out server-side; re-enter the queue
      continue
    fi
    printf '%s\n' "$body" >&2
    return 1
  done
}

release() {
  curl -fsS -X DELETE "$API/leases/$1"
  echo
}

status() {
  if command -v jq >/dev/null 2>&1; then
    curl -fsS "$API/state" | jq .
  else
    curl -fsS "$API/state"
    echo
  fi
}

run() {
  local holder=$1 kind=$2 ttl=300
  shift 2
  while [[ $# -gt 0 && $1 != -- ]]; do
    case $1 in
      --ttl) ttl=$2; shift 2 ;;
      *) usage ;;
    esac
  done
  [[ ${1:-} == -- && $# -ge 2 ]] || usage
  shift
  need_jq
  acquire "$holder" "$kind" true "$ttl" >/dev/null
  echo "gpu-lock: lease acquired by '$holder' (kind=$kind, ttl=${ttl}s)" >&2
  local interval=$(( ttl / 3 > 5 ? ttl / 3 : 5 ))
  (
    while :; do
      sleep "$interval"
      curl -fsS -X POST "$API/leases/$holder/heartbeat" >/dev/null 2>&1 || true
    done
  ) &
  # Globals, not locals: the EXIT trap fires after run() returns, when locals
  # are already out of scope.
  HEARTBEAT_PID=$!
  LOCK_HOLDER=$holder
  cleanup() {
    kill "$HEARTBEAT_PID" 2>/dev/null || true
    curl -fsS -X DELETE "$API/leases/$LOCK_HOLDER" >/dev/null 2>&1 || true
  }
  trap cleanup EXIT
  "$@"
}

[[ $# -ge 1 ]] || usage
cmd=$1; shift
case $cmd in
  acquire)
    [[ $# -ge 2 ]] || usage
    holder=$1 kind=$2; shift 2
    wait=false ttl=120
    while [[ $# -gt 0 ]]; do
      case $1 in
        --wait) wait=true; shift ;;
        --ttl) ttl=$2; shift 2 ;;
        *) usage ;;
      esac
    done
    need_jq
    acquire "$holder" "$kind" "$wait" "$ttl"
    ;;
  release)
    [[ $# -eq 1 ]] || usage
    release "$1"
    ;;
  status)
    [[ $# -eq 0 ]] || usage
    status
    ;;
  run)
    [[ $# -ge 2 ]] || usage
    run "$@"
    ;;
  *)
    usage
    ;;
esac
