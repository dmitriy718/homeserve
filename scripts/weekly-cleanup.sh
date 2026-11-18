#!/usr/bin/env bash
# Weekly filesystem maintenance for homeserv (ai-node).
# Prunes unused Docker images/build cache/dangling volumes, rotates local
# backup archives (>7 days, keeping newest 3) and site_fleet backups (>7 days,
# keeping newest 6 per site), and clears temporary/package caches.
set -euo pipefail

ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "[$ts] Starting weekly homeserv filesystem cleanup..."
df -h /

# 1. Prune unused Docker build cache, unused images (>7d), exited containers (>7d), and dangling volumes
if command -v docker >/dev/null 2>&1; then
  docker container prune -f --filter "until=168h" || true
  docker image prune -af --filter "until=168h" || true
  docker builder prune -af --filter "until=168h" || true
  docker volume prune -f || true
fi

# 2. Prune local ai-node backup archives older than 7 days (always keep newest 3)
backup_dest=/srv/backups/local
if [[ -d $backup_dest ]]; then
  cutoff=$(( $(date +%s) - 7 * 86400 ))
  index=0
  while IFS= read -r old_archive; do
    [[ -n $old_archive ]] || continue
    index=$((index + 1))
    ((index > 3)) || continue
    if (( $(stat -c %Y "$old_archive") < cutoff )); then
      echo "Removing expired backup archive: $old_archive"
      rm -f -- "$old_archive" "$old_archive.sha256"
    fi
  done < <(find "$backup_dest" -maxdepth 1 -type f -name 'ai-node-*.tar.zst' -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
  find "$backup_dest" -maxdepth 1 -type f -name 'ai-node-*.partial' -mtime +1 -delete 2>/dev/null || true
fi

# 3. Prune site_fleet zip backups older than 7 days (always keep newest 6 per site)
site_fleet_dir=/srv/ai-node/data/backups/site_fleet
if [[ -d $site_fleet_dir ]]; then
  cutoff_sf=$(( $(date +%s) - 7 * 86400 ))
  for site_dir in "$site_fleet_dir"/*; do
    [[ -d $site_dir ]] || continue
    idx=0
    while IFS= read -r zip_file; do
      [[ -n $zip_file ]] || continue
      idx=$((idx + 1))
      ((idx > 6)) || continue
      if (( $(stat -c %Y "$zip_file") < cutoff_sf )); then
        echo "Removing expired site_fleet backup: $zip_file"
        rm -f -- "$zip_file"
      fi
    done < <(find "$site_dir" -maxdepth 1 -type f -name 'backup_*.zip' -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
  done
fi

# 4. Clean user & application temporary caches
rm -rf /home/dima/.cache/pip/* /home/dima/.npm/_cacache/* 2>/dev/null || true
rm -rf /srv/ai-node/data/comfyui/cache/* 2>/dev/null || true
find /tmp -maxdepth 1 -user dima \( -name 'pytest-*' -o -name 'playwright*' -o -name 'ai-node-restore-test.*' \) -mtime +1 -exec rm -rf -- {} + 2>/dev/null || true

# 5. Publish Prometheus textfile metric if writable
metrics_dir=/srv/ai-node/data/node-exporter-textfile
if [[ -d $metrics_dir && -w $metrics_dir ]]; then
  metrics_tmp=$(mktemp "$metrics_dir/weekly-cleanup.XXXXXX")
  avail_bytes=$(df -B1 --output=avail / | awk 'NR==2 {print $1}')
  printf '# HELP ai_node_weekly_cleanup_last_success_unixtime_seconds Unix time of the last weekly filesystem cleanup.\n# TYPE ai_node_weekly_cleanup_last_success_unixtime_seconds gauge\nai_node_weekly_cleanup_last_success_unixtime_seconds %s\n# HELP ai_node_root_free_bytes Available bytes on root filesystem after weekly cleanup.\n# TYPE ai_node_root_free_bytes gauge\nai_node_root_free_bytes %s\n' \
    "$(date +%s)" "$avail_bytes" >"$metrics_tmp"
  chmod 0644 "$metrics_tmp"
  mv -- "$metrics_tmp" "$metrics_dir/weekly-cleanup.prom"
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Weekly cleanup complete."
df -h /
