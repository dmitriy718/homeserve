#!/usr/bin/env bash
set -euo pipefail

# Monthly restore verification for local backups.
# Runs from ai-node-restore-test.timer. Takes the newest archive in
# /srv/backups/local, verifies its SHA-256 sidecar, extracts to a scratch
# directory, spot-checks critical content, and checks the Grafana SQLite
# database when sqlite3 is available. Publishes a Prometheus result metric
# and exits non-zero on failure so the systemd unit records it.

if ((EUID != 0)); then
  exec sudo -- "$0" "$@"
fi

backup_dir=${BACKUP_DEST:-/srv/backups/local}
metrics_dir=/srv/ai-node/data/node-exporter-textfile
success=0
scratch=""

install -d -m 0755 /run/lock/ai-node
exec 9>/run/lock/ai-node/restore-test.lock
flock -n 9 || { echo "Another restore test is running" >&2; exit 1; }

publish_metrics() {
  local metrics_tmp
  if install -d -m 0755 "$metrics_dir" && metrics_tmp=$(mktemp "$metrics_dir/restore-test.XXXXXX"); then
    if printf '%s\n' \
        '# HELP ai_node_restore_test_success Result of the last automated restore test (1 = passed).' \
        '# TYPE ai_node_restore_test_success gauge' \
        "ai_node_restore_test_success $success" \
        '# HELP ai_node_restore_test_last_run_unixtime_seconds Unix time of the last automated restore test.' \
        '# TYPE ai_node_restore_test_last_run_unixtime_seconds gauge' \
        "ai_node_restore_test_last_run_unixtime_seconds $(date +%s)" \
        >"$metrics_tmp" \
        && chmod 0644 "$metrics_tmp" \
        && mv -- "$metrics_tmp" "$metrics_dir/restore-test.prom"; then
      return 0
    fi
    rm -f -- "$metrics_tmp"
  fi
  echo "WARNING: publishing restore-test metrics failed" >&2
}

cleanup() {
  [[ -z $scratch ]] || rm -rf -- "$scratch"
  publish_metrics
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

archive=$(find "$backup_dir" -maxdepth 1 -type f -name 'ai-node-*.tar.zst' -printf '%T@ %p\n' \
  | sort -rn | head -n1 | cut -d' ' -f2-)
[[ -n $archive ]] || { echo "No backup archives found in $backup_dir" >&2; exit 1; }
[[ -f $archive.sha256 ]] || { echo "Missing checksum sidecar: $archive.sha256" >&2; exit 1; }

# Verify the archive checksum before extracting anything.
(
  cd "$backup_dir"
  sha256sum -c "$(basename "$archive").sha256" >/dev/null
)

scratch=$(mktemp -d /tmp/ai-node-restore-test.XXXXXX)
chmod 0700 "$scratch"
if ! tar --zstd --acls --xattrs -xpf "$archive" -C "$scratch"; then
  echo "Restore test failed: could not extract $archive" >&2
  exit 1
fi

# Spot-check critical paths.
failures=0
if [[ ! -f $scratch/ai-node/data/grafana/grafana.db && ! -d $scratch/ai-node/data/grafana ]]; then
  echo "MISSING: grafana database or data directory" >&2
  failures=$((failures + 1))
fi
if [[ ! -d $scratch/ai-node/data/open-webui ]]; then
  echo "MISSING: open-webui data directory" >&2
  failures=$((failures + 1))
fi
if [[ ! -d $scratch/ai-node/secrets ]]; then
  echo "MISSING: secrets directory" >&2
  failures=$((failures + 1))
fi
((failures == 0)) || { echo "Restore test failed: $failures critical path(s) missing" >&2; exit 1; }

# Verify the Grafana SQLite database opens cleanly when sqlite3 is available.
if command -v sqlite3 >/dev/null && [[ -f $scratch/ai-node/data/grafana/grafana.db ]]; then
  if ! sqlite3 "$scratch/ai-node/data/grafana/grafana.db" 'PRAGMA quick_check;' | grep -qx 'ok'; then
    echo "Restore test failed: grafana.db failed SQLite quick_check" >&2
    exit 1
  fi
fi

success=1
echo "Restore test passed: $archive"
