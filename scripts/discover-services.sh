#!/usr/bin/env bash
# discover-services.sh — derive Prometheus blackbox probe targets from
# running containers' homeserv.* labels.
# See docs/APP_MANIFEST.md for the label contract.
#
# Writes (atomically, and only when Docker is reachable):
#   <repo>/monitoring/targets.d/probes.json   Prometheus file_sd target groups
# On the host the repo lives at /srv/ai-node; monitoring/targets.d is
# bind-mounted into the prometheus container at /etc/prometheus/targets.d.
#
# Degrades gracefully: if Docker is unreachable or no labeled containers are
# running, exits 0 and leaves any previously generated files untouched.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
targets_dir="$repo_root/monitoring/targets.d"

if ! docker ps >/dev/null 2>&1; then
  echo "discover-services: docker unreachable; leaving existing files untouched" >&2
  exit 0
fi

ids=$(docker ps -q --filter label=homeserv.name)
if [[ -z $ids ]]; then
  echo "discover-services: no running containers with homeserv.name labels; leaving existing files untouched" >&2
  exit 0
fi

# ids is a whitespace-separated list of container IDs from docker ps.
# shellcheck disable=SC2086
inspect=$(docker inspect $ids)

install -d -m 0755 "$targets_dir"

# Write stdin to $1 via a temp file + rename so consumers never see a partial
# file. The temp name never matches Prometheus' *.json file_sd glob.
write_atomic() {
  local dest=$1 tmp
  tmp=$(mktemp "$dest.XXXXXX")
  cat >"$tmp"
  chmod 0644 "$tmp"
  mv -- "$tmp" "$dest"
}

# Prometheus file_sd target groups, one per probed container. Targets are
# full URLs: the blackbox relabeling moves __address__ to __param_target,
# exactly like the static blackbox_http job. Capture jq's output first so a
# failed jq never clobbers the previous good file with partial/empty stdout.
if probes=$(jq '[ .[] | .Config.Labels as $l
      | select($l["homeserv.probe.url"] != null)
      | { targets: [$l["homeserv.probe.url"]],
          labels: { service: ($l["com.docker.compose.service"] // (.Name | ltrimstr("/"))),
                    name: $l["homeserv.name"] } } ]
    | sort_by(.labels.name)' <<<"$inspect") && [[ -n $probes ]]; then
  write_atomic "$targets_dir/probes.json" <<<"$probes"
  echo "discover-services: updated $targets_dir/probes.json"
else
  echo "discover-services: jq failed or produced no output; leaving existing probes.json untouched" >&2
fi
