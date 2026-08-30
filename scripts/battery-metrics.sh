#!/usr/bin/env bash
set -euo pipefail

# Publish laptop battery metrics to the node-exporter textfile directory.
# The battery acts as a de-facto UPS; monitoring it detects power outages.
# Runs from ai-node-battery-metrics.timer (every 2 minutes).
# Hosts without a battery publish ai_node_battery_present 0 and exit 0.

metrics_dir=/srv/ai-node/data/node-exporter-textfile
present=0
capacity=0
on_ac=1

for bat in /sys/class/power_supply/BAT*; do
  [[ -d $bat ]] || continue
  present=1
  capacity=$(<"$bat/capacity")
  break
done

if ((present)); then
  [[ $capacity =~ ^[0-9]+$ ]] || { echo "Could not parse battery capacity" >&2; exit 1; }
  on_ac=0
  for ac in /sys/class/power_supply/AC*/online /sys/class/power_supply/ADP*/online; do
    [[ -f $ac ]] || continue
    if [[ $(<"$ac") == 1 ]]; then
      on_ac=1
      break
    fi
  done
fi

# Atomic publish: write to a temp file in the same directory, then mv.
if install -d -m 0755 "$metrics_dir" && metrics_tmp=$(mktemp "$metrics_dir/battery.XXXXXX"); then
  if printf '%s\n' \
      '# HELP ai_node_battery_present Whether the host has a battery (1 = laptop with battery).' \
      '# TYPE ai_node_battery_present gauge' \
      "ai_node_battery_present $present" \
      '# HELP ai_node_battery_capacity_percent Battery charge level in percent.' \
      '# TYPE ai_node_battery_capacity_percent gauge' \
      "ai_node_battery_capacity_percent $capacity" \
      '# HELP ai_node_battery_on_ac Whether the host is on AC power (1 = on AC, 0 = on battery).' \
      '# TYPE ai_node_battery_on_ac gauge' \
      "ai_node_battery_on_ac $on_ac" \
      >"$metrics_tmp" \
      && chmod 0644 "$metrics_tmp" \
      && mv -- "$metrics_tmp" "$metrics_dir/battery.prom"; then
    :
  else
    rm -f -- "$metrics_tmp"
    echo "ERROR: publishing battery metrics failed" >&2
    exit 1
  fi
else
  echo "ERROR: creating battery metrics file failed" >&2
  exit 1
fi
