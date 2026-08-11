#!/usr/bin/env bash
set -uo pipefail

echo "AI node status - $(date --iso-8601=seconds)"
echo "Hostname: $(hostname)"
echo "Uptime/load: $(uptime -p); $(cut -d' ' -f1-3 /proc/loadavg)"
free -h
df -hT / /srv 2>/dev/null | awk 'NR==1 || !seen[$1]++'
echo
echo "Temperatures:"
sensors 2>/dev/null | awk '/Tctl:|Composite:|edge:|temp1:/{print}' | head -n 12 || true
echo
echo "NVIDIA GPU:"
nvidia-smi --query-gpu=name,driver_version,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw --format=csv,noheader 2>&1 || true
echo
echo "Docker:"
docker info --format 'Server {{.ServerVersion}}; containers={{.Containers}} running={{.ContainersRunning}}' 2>&1 || true
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>&1 || true
unhealthy=$(docker ps --filter health=unhealthy --format '{{.Names}}' 2>/dev/null || true)
if [[ -n $unhealthy ]]; then
  echo "Unhealthy containers:"
  while IFS= read -r container; do
    printf '  %s\n' "$container"
  done <<<"$unhealthy"
fi
echo
echo "Backup:"
latest_backup=$(find /srv/backups/local -maxdepth 1 -type f -name 'ai-node-*.tar.zst' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2-)
if [[ -n $latest_backup ]]; then
  backup_age=$(( ($(date +%s) - $(stat -c %Y "$latest_backup")) / 3600 ))
  echo "Latest local backup: $latest_backup (${backup_age}h old)"
else
  echo "Latest local backup: none"
fi
if [[ -e /var/run/reboot-required ]]; then
  echo "Reboot required: yes"
else
  echo "Reboot required: no"
fi
echo
echo "Tailscale:"
tailscale status --self 2>&1 || true
echo
echo "Failed systemd units:"
systemctl --failed --no-pager 2>&1 || true
