#!/usr/bin/env bash
set -euo pipefail

source /srv/ai-node/.env

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

