#!/usr/bin/env bash
set -euo pipefail

# Publish NVMe SMART metrics to the node-exporter textfile directory.
# Runs from ai-node-smart-metrics.timer (hourly); requires smartmontools.

device=${SMART_DEVICE:-/dev/nvme0}
metrics_dir=/srv/ai-node/data/node-exporter-textfile

command -v smartctl >/dev/null || { echo "smartctl is not installed (smartmontools)" >&2; exit 1; }
# NVMe controllers (/dev/nvme0) are character devices; SATA/SAS drives are
# block devices — accept either.
[[ -b $device || -c $device ]] || { echo "SMART device not found: $device" >&2; exit 1; }

if ! smartctl -H "$device" | grep -q 'PASSED'; then
  echo "WARNING: overall SMART health is not PASSED for $device" >&2
fi

attributes=$(smartctl -A "$device")
media_errors=$(awk -F: '/^Media and Data Integrity Errors:/ {gsub(/[ ,]/, "", $2); print $2}' <<<"$attributes")
percentage_used=$(awk -F: '/^Percentage Used:/ {gsub(/[ %]/, "", $2); print $2}' <<<"$attributes")
critical_warning=$(awk -F: '/^Critical Warning:/ {gsub(/ /, "", $2); print $2}' <<<"$attributes")

[[ $media_errors =~ ^[0-9]+$ ]] || { echo "Could not parse NVMe media errors from smartctl output" >&2; exit 1; }
[[ $percentage_used =~ ^[0-9]+$ ]] || { echo "Could not parse NVMe percentage used from smartctl output" >&2; exit 1; }
[[ $critical_warning =~ ^0x[0-9a-fA-F]+$ ]] || { echo "Could not parse NVMe critical warning from smartctl output" >&2; exit 1; }
critical_warning=$((critical_warning))

# Atomic publish: write to a temp file in the same directory, then mv.
if install -d -m 0755 "$metrics_dir" && metrics_tmp=$(mktemp "$metrics_dir/smart.XXXXXX"); then
  if printf '%s\n' \
      '# HELP ai_node_nvme_media_errors Media and data integrity errors reported by the NVMe device.' \
      '# TYPE ai_node_nvme_media_errors gauge' \
      "ai_node_nvme_media_errors $media_errors" \
      '# HELP ai_node_nvme_percentage_used Percentage of the NVMe device rated endurance consumed.' \
      '# TYPE ai_node_nvme_percentage_used gauge' \
      "ai_node_nvme_percentage_used $percentage_used" \
      '# HELP ai_node_nvme_critical_warning NVMe critical warning bitfield (non-zero requires immediate attention).' \
      '# TYPE ai_node_nvme_critical_warning gauge' \
      "ai_node_nvme_critical_warning $critical_warning" \
      >"$metrics_tmp" \
      && chmod 0644 "$metrics_tmp" \
      && mv -- "$metrics_tmp" "$metrics_dir/smart.prom"; then
    :
  else
    rm -f -- "$metrics_tmp"
    echo "ERROR: publishing NVMe SMART metrics failed" >&2
    exit 1
  fi
else
  echo "ERROR: creating NVMe SMART metrics file failed" >&2
  exit 1
fi
