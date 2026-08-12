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
    "${compose[@]}" unpause "${paused[@]}" >/dev/null 2>&1 || true
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

for service in agent-gateway open-webui comfyui grafana uptime-kuma speedtest-tracker; do
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

find "$backup_dest" -maxdepth 1 -type f \
  \( -name 'ai-node-*.tar.zst' -o -name 'ai-node-*.tar.zst.sha256' -o -name 'ai-node-*.partial' \) \
  -mtime +14 -delete
echo "Created $archive"
if [[ $backup_dest == /srv/backups/* ]]; then
  echo "WARNING: this backup is on the same SSD and does not protect against drive failure."
fi
