#!/usr/bin/env bash
# Opt-in scheduled stack update, run weekly by ai-node-update.timer.
# Enable with:  touch /srv/ai-node/.auto-update
# Disable with: rm /srv/ai-node/.auto-update
# Without the flag file this script exits 0 quietly.
set -uo pipefail

flag=/srv/ai-node/.auto-update
[[ -f $flag ]] || exit 0

if ((EUID != 0)); then
  exec sudo -- "$0" "$@"
fi

success=0
if /srv/ai-node/scripts/update-stack.sh; then
  success=1
fi

# Publish the result for node-exporter's textfile collector (same atomic
# mktemp + mv pattern as scripts/backup.sh).
metrics_dir=/srv/ai-node/data/node-exporter-textfile
if install -d -m 0755 "$metrics_dir" && metrics_tmp=$(mktemp "$metrics_dir/auto-update.XXXXXX"); then
  if printf '# HELP ai_node_last_update_success Whether the last scheduled stack update succeeded (1) or failed (0).\n# TYPE ai_node_last_update_success gauge\nai_node_last_update_success %s\n# HELP ai_node_last_update_unixtime_seconds Unix time of the last scheduled stack update attempt.\n# TYPE ai_node_last_update_unixtime_seconds gauge\nai_node_last_update_unixtime_seconds %s\n' \
      "$success" "$(date +%s)" >"$metrics_tmp" \
      && chmod 0644 "$metrics_tmp" \
      && mv -- "$metrics_tmp" "$metrics_dir/auto-update.prom"; then
    :
  else
    rm -f -- "$metrics_tmp"
    echo "WARNING: publishing the update Prometheus metric failed" >&2
  fi
else
  echo "WARNING: creating the update Prometheus metric failed" >&2
fi

if ((success == 0)); then
  # Best-effort push notification; never mask the failure exit code.
  if command -v curl >/dev/null; then
    curl -fsS -m 10 -H 'X-Priority: 5' \
      -d "ai-node scheduled update FAILED; inspect with: journalctl -u ai-node-update.service" \
      http://localhost:2586/homeserve-alerts-critical || true
  fi
  exit 1
fi
