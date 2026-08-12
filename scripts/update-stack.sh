#!/usr/bin/env bash
set -euo pipefail

runtime_dir=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
if [[ ! -d $runtime_dir || ! -w $runtime_dir ]]; then
  runtime_dir=/tmp
fi
exec 9>"$runtime_dir/ai-node-update-$(id -u).lock"
flock -n 9 || { echo "Another stack update is running" >&2; exit 1; }

cd /srv/ai-node/compose
/srv/ai-node/scripts/validate-config.sh --strict
compose=(docker compose --env-file ../.env -f ai-node.yml)
declare -A previous_image_ids=()

while IFS=$'\t' read -r service image_ref; do
  container=$("${compose[@]}" ps -q "$service")
  if [[ -n $container ]]; then
    previous_image_ids["$image_ref"]=$(docker inspect -f '{{.Image}}' "$container")
  fi
done < <("${compose[@]}" config --format json | jq -r '.services | to_entries[] | [.key, .value.image] | @tsv')

restore_image_tags() {
  local image_ref
  echo "Restoring pre-update image tags..." >&2
  for image_ref in "${!previous_image_ids[@]}"; do
    docker image tag "${previous_image_ids[$image_ref]}" "$image_ref"
  done
}

rollback_running_stack() {
  restore_image_tags
  echo "Recreating the previous stack..." >&2
  "${compose[@]}" up -d --remove-orphans
  /srv/ai-node/scripts/wait-stack-healthy.sh
}

if ! "${compose[@]}" pull --ignore-buildable; then
  restore_image_tags
  exit 1
fi
if ! "${compose[@]}" build --pull; then
  restore_image_tags
  exit 1
fi
if ! /srv/ai-node/scripts/validate-config.sh --strict; then
  restore_image_tags
  exit 1
fi
if ! "${compose[@]}" up -d --remove-orphans; then
  rollback_running_stack || echo "ERROR: automatic rollback failed" >&2
  exit 1
fi
if ! /srv/ai-node/scripts/wait-stack-healthy.sh; then
  rollback_running_stack || echo "ERROR: automatic rollback failed" >&2
  exit 1
fi
echo "Unused images/build cache were not deleted automatically. Review with: docker system df"
