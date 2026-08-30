#!/usr/bin/env bash
set -euo pipefail

if ((EUID != 0)); then
  exec sudo -- "$0" "$@"
fi

backup_dest=${BACKUP_DEST:-/srv/backups/local}
case "$backup_dest" in
  /srv/backups/*|/mnt/*|/media/*) ;;
  *) echo "Refusing unexpected BACKUP_DEST: $backup_dest" >&2; exit 2 ;;
esac

mkdir -p "$backup_dest"
chmod 0700 "$backup_dest"
if [[ $backup_dest == /mnt/* || $backup_dest == /media/* ]]; then
  root_device=$(stat -c '%d' /)
  backup_device=$(stat -c '%d' "$backup_dest")
  if [[ $root_device == "$backup_device" ]]; then
    echo "Refusing external backup path on the root filesystem: $backup_dest" >&2
    echo "Mount the external disk or NAS first." >&2
    exit 2
  fi
fi
install -d -m 0755 /run/lock/ai-node
exec 9>/run/lock/ai-node/backup.lock
flock -n 9 || { echo "Another backup is running" >&2; exit 1; }

# Pre-flight: refuse to start without room for the archive.
# Require at least 10 GiB free, or 1.5x the newest previous archive if larger.
required_free=$((10 * 1024 * 1024 * 1024))
newest_size=$(find "$backup_dest" -maxdepth 1 -type f -name 'ai-node-*.tar.zst' -printf '%T@ %s\n' \
  | sort -rn | head -n1 | cut -d' ' -f2)
if [[ ${newest_size:-} =~ ^[0-9]+$ ]]; then
  estimated=$((newest_size + newest_size / 2))
  ((estimated > required_free)) && required_free=$estimated
fi
free_bytes=$(df -B1 --output=avail "$backup_dest" | awk 'NR==2 {print $1}')
if [[ $free_bytes =~ ^[0-9]+$ ]] && ((free_bytes < required_free)); then
  echo "Not enough free space at $backup_dest: $((free_bytes / 1024 / 1024 / 1024)) GiB available," \
    "need at least $((required_free / 1024 / 1024 / 1024)) GiB" >&2
  exit 1
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
archive="$backup_dest/ai-node-$stamp.tar.zst"
partial="$archive.partial"
checksum="$archive.sha256"
checksum_partial="$checksum.partial"
status_tmp=""
finalized=false
compose=(docker compose --env-file /srv/ai-node/.env -f /srv/ai-node/compose/ai-node.yml)
paused=()

unpause_services() {
  if ((${#paused[@]})); then
    local attempt
    for attempt in 1 2 3 4 5; do
      if "${compose[@]}" unpause "${paused[@]}"; then
        paused=()
        return 0
      fi
      echo "WARNING: unpause attempt $attempt failed; retrying in 2s" >&2
      sleep 2
    done
    echo "ERROR: services may still be paused: ${paused[*]} (run: docker compose unpause ${paused[*]})" >&2
    paused=()
  fi
}

cleanup() {
  unpause_services
  rm -f -- "$partial" "$checksum_partial"
  [[ -z $status_tmp ]] || rm -f -- "$status_tmp"
  if ! $finalized; then
    rm -f -- "$archive" "$checksum"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Services to pause during the archive: derived from the
# homeserv.backup.pause=true container label (docs/APP_MANIFEST.md), with a
# static fallback when Docker or the labels are unavailable.
pause_services=()
if docker info >/dev/null 2>&1; then
  while IFS= read -r svc; do
    [[ -n $svc ]] && pause_services+=("$svc")
  done < <(docker ps --filter label=com.docker.compose.project=ai-node \
      --filter label=homeserv.backup.pause=true \
      --format '{{index .Labels "com.docker.compose.service"}}' | sort -u)
fi
if ((${#pause_services[@]} == 0)); then
  pause_services=(agent-gateway open-webui comfyui grafana uptime-kuma speedtest-tracker)
fi

for service in "${pause_services[@]}"; do
  container=$("${compose[@]}" ps -q "$service")
  if [[ -n $container ]] && [[ $(docker inspect -f '{{.State.Running}}' "$container") == true ]]; then
    "${compose[@]}" pause "$service" >/dev/null
    paused+=("$service")
  fi
done

if ! tar --zstd --acls --xattrs -cpf "$partial" \
  --exclude='ai-node/data/prometheus' \
  --exclude='ai-node/data/open-webui/cache' \
  --exclude='ai-node/data/grafana/plugins' \
  --exclude='ai-node/data/backup-status' \
  --exclude='ai-node/data/node-exporter-textfile' \
  --exclude='ai-node/logs' \
  --exclude='ai-node/agent-platform/cache' \
  --exclude='backups' \
  -C /srv ai-node repos; then
  exit 1
fi
chmod 0600 "$partial"
if ! tar --zstd -tf "$partial" >/dev/null; then
  echo "Backup verification failed: $partial" >&2
  exit 1
fi
mv -- "$partial" "$archive"
unpause_services

sha256sum "$archive" > "$checksum_partial"
chmod 0600 "$checksum_partial"
mv -- "$checksum_partial" "$checksum"
(
  cd "$backup_dest"
  sha256sum -c "$(basename "$checksum")" >/dev/null
)

status_dir=/srv/ai-node/data/backup-status
install -d -m 0755 "$status_dir"
status_tmp=$(mktemp "$status_dir/last-success.XXXXXX")
printf 'timestamp=%s\narchive=%s\nchecksum=%s\n' \
  "$(date +%s)" "$archive" "$checksum" >"$status_tmp"
chmod 0644 "$status_tmp"
mv -- "$status_tmp" "$status_dir/last-success"
status_tmp=""
finalized=true
trap - EXIT INT TERM

metrics_dir=/srv/ai-node/data/node-exporter-textfile
if install -d -m 0755 "$metrics_dir" && metrics_tmp=$(mktemp "$metrics_dir/backup.XXXXXX"); then
  if printf '# HELP ai_node_backup_last_success_unixtime_seconds Unix time of the last verified backup.\n# TYPE ai_node_backup_last_success_unixtime_seconds gauge\nai_node_backup_last_success_unixtime_seconds %s\n' \
      "$(date +%s)" >"$metrics_tmp" \
      && chmod 0644 "$metrics_tmp" \
      && mv -- "$metrics_tmp" "$metrics_dir/backup.prom"; then
    :
  else
    rm -f -- "$metrics_tmp"
    echo "WARNING: backup succeeded but publishing its Prometheus metric failed" >&2
  fi
else
  echo "WARNING: backup succeeded but creating its Prometheus metric failed" >&2
fi

# Retention: expire archives older than 14 days, but always keep the newest 3.
cutoff=$(( $(date +%s) - 14 * 86400 ))
index=0
while IFS= read -r old_archive; do
  index=$((index + 1))
  ((index > 3)) || continue
  if (( $(stat -c %Y "$old_archive") < cutoff )); then
    rm -f -- "$old_archive" "$old_archive.sha256"
  fi
done < <(find "$backup_dest" -maxdepth 1 -type f -name 'ai-node-*.tar.zst' -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
find "$backup_dest" -maxdepth 1 -type f -name 'ai-node-*.partial' -mtime +14 -delete
echo "Created $archive"
if [[ $backup_dest == /srv/backups/* ]]; then
  echo "WARNING: this backup is on the same SSD and does not protect against drive failure."
fi
