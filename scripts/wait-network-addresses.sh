#!/usr/bin/env bash
set -euo pipefail

# Extract a VAR=value from .env without sourcing it (the file is config, not code).
env_value() {
  local line
  line=$(grep -E "^$1=" /srv/ai-node/.env | tail -n1) || return 1
  [[ $line =~ ^[A-Z_]+=[a-zA-Z0-9./:-]+$ ]] || return 1
  printf '%s' "${line#*=}"
}

LAN_IP=$(env_value LAN_IP) || { echo "LAN_IP missing or invalid in /srv/ai-node/.env" >&2; exit 1; }
TAILSCALE_IP=$(env_value TAILSCALE_IP) || { echo "TAILSCALE_IP missing or invalid in /srv/ai-node/.env" >&2; exit 1; }

for _ in $(seq 1 120); do
  addresses=$(ip -4 -o address show | awk '{print $4}' | cut -d/ -f1)
  if grep -Fxq "$LAN_IP" <<<"$addresses" && grep -Fxq "$TAILSCALE_IP" <<<"$addresses"; then
    echo "Required addresses ready: LAN=$LAN_IP Tailscale=$TAILSCALE_IP"
    exit 0
  fi
  sleep 1
done

echo "Timed out waiting for LAN=$LAN_IP and Tailscale=$TAILSCALE_IP" >&2
exit 1
