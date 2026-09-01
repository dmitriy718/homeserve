#!/usr/bin/env bash
set -euo pipefail

# Encrypted offsite backup of /srv/ai-node via restic.
# Runs from ai-node-offsite-backup.timer (daily, after the local backup).
# Configure by creating /srv/ai-node/secrets/restic.env with RESTIC_REPOSITORY
# (see secrets/restic.env.example). Until configured this script exits 0.

if ((EUID != 0)); then
  exec sudo -- "$0" "$@"
fi

[[ -f /srv/ai-node/compose/ai-node.yml ]] || { echo "must run on the ai-node host" >&2; exit 1; }

env_file=/srv/ai-node/secrets/restic.env
if [[ -f $env_file ]]; then
  # shellcheck source=/dev/null
  source "$env_file"
fi

if [[ -z ${RESTIC_REPOSITORY:-} ]]; then
  echo "Offsite backup not configured (RESTIC_REPOSITORY unset in $env_file); skipping."
  exit 0
fi

command -v restic >/dev/null || { echo "restic is not installed" >&2; exit 1; }

export RESTIC_PASSWORD_FILE=${RESTIC_PASSWORD_FILE:-/srv/ai-node/secrets/restic-password}
export RESTIC_REPOSITORY

install -d -m 0755 /run/lock/ai-node
exec 9>/run/lock/ai-node/backup-offsite.lock
flock -n 9 || { echo "Another offsite backup is running" >&2; exit 1; }

# First run: generate the encryption password and initialize the repository.
if [[ ! -f $RESTIC_PASSWORD_FILE ]]; then
  echo "First run: generating $RESTIC_PASSWORD_FILE and initializing the repository."
  openssl rand -hex 32 > "$RESTIC_PASSWORD_FILE"
  chmod 0600 "$RESTIC_PASSWORD_FILE"
  restic init
fi

# Same exclude philosophy as scripts/backup.sh: no Prometheus history,
# downloadable caches, logs, or metric scratch state.
restic backup \
  --exclude='/srv/ai-node/data/prometheus' \
  --exclude='/srv/ai-node/data/open-webui/cache' \
  --exclude='/srv/ai-node/data/grafana/plugins' \
  --exclude='/srv/ai-node/data/backup-status' \
  --exclude='/srv/ai-node/data/node-exporter-textfile' \
  --exclude='/srv/ai-node/logs' \
  --exclude='/srv/ai-node/agent-platform/cache' \
  /srv/ai-node

restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune

snapshots_total=$(restic snapshots --json | jq 'length')
[[ $snapshots_total =~ ^[0-9]+$ ]] || { echo "Could not parse snapshot count" >&2; exit 1; }

# Atomic publish: write to a temp file in the same directory, then mv.
metrics_dir=/srv/ai-node/data/node-exporter-textfile
if install -d -m 0755 "$metrics_dir" && metrics_tmp=$(mktemp "$metrics_dir/offsite-backup.XXXXXX"); then
  if printf '%s\n' \
      '# HELP ai_node_offsite_backup_last_success_unixtime_seconds Unix time of the last verified offsite backup.' \
      '# TYPE ai_node_offsite_backup_last_success_unixtime_seconds gauge' \
      "ai_node_offsite_backup_last_success_unixtime_seconds $(date +%s)" \
      '# HELP ai_node_offsite_backup_snapshots_total Snapshots currently kept in the offsite repository.' \
      '# TYPE ai_node_offsite_backup_snapshots_total gauge' \
      "ai_node_offsite_backup_snapshots_total $snapshots_total" \
      >"$metrics_tmp" \
      && chmod 0644 "$metrics_tmp" \
      && mv -- "$metrics_tmp" "$metrics_dir/offsite-backup.prom"; then
    :
  else
    rm -f -- "$metrics_tmp"
    echo "ERROR: publishing offsite backup metrics failed" >&2
    exit 1
  fi
else
  echo "ERROR: creating offsite backup metrics file failed" >&2
  exit 1
fi

echo "Offsite backup complete: $snapshots_total snapshots in $RESTIC_REPOSITORY"
