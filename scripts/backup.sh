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
compose=(docker compose --env-file /srv/ai-node/.env -f /srv/ai-node/compose/ai-node.yml)
paused=()

cleanup() {
  if ((${#paused[@]})); then
    "${compose[@]}" unpause "${paused[@]}" >/dev/null 2>&1 || true
  fi
  rm -f -- "$partial"
}
trap cleanup EXIT INT TERM

for service in open-webui grafana uptime-kuma speedtest-tracker; do
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
cleanup
paused=()
trap - EXIT INT TERM

sha256sum "$archive" > "$archive.sha256"
chmod 0600 "$archive.sha256"
(
  cd "$backup_dest"
  sha256sum -c "$(basename "$archive.sha256")" >/dev/null
)
find "$backup_dest" -maxdepth 1 -type f \
  \( -name 'ai-node-*.tar.zst' -o -name 'ai-node-*.tar.zst.sha256' -o -name 'ai-node-*.tar.zst.partial' \) \
  -mtime +14 -delete
echo "Created $archive"
if [[ $backup_dest == /srv/backups/* ]]; then
  echo "WARNING: this backup is on the same SSD and does not protect against drive failure."
fi
