#!/usr/bin/env bash
set -euo pipefail

if ((EUID != 0)); then
  exec sudo -- "$0" "$@"
fi

skip_backup=false
force=false
for arg in "$@"; do
  case $arg in
    --skip-backup) skip_backup=true ;;
    --force) force=true ;;
    *) echo "Usage: $0 [--skip-backup] [--force]" >&2; exit 2 ;;
  esac
done

install -d -m 0755 /run/lock/ai-node
exec 9>/run/lock/ai-node/update.lock
flock -n 9 || { echo "Another stack update is running" >&2; exit 1; }

# Snapshot configuration and state before touching the stack so that a
# failed update can be recovered with both images and data.
if ! $skip_backup; then
  if ! /srv/ai-node/scripts/backup.sh; then
    if $force; then
      echo "WARNING: pre-update backup failed; continuing because --force was given" >&2
    else
      echo "ERROR: pre-update backup failed; aborting update (use --force to override or --skip-backup to skip)" >&2
      exit 1
    fi
  fi
fi

cd /srv/ai-node/compose
/srv/ai-node/scripts/validate-config.sh --strict

# Include any apps/ overlay files that are actually in use, so that
# `up -d --remove-orphans` does not prune app containers. The set of active
# compose files is read back from a running container's own labels; fall back
# to the base file only.
compose=(docker compose --env-file ../.env)
config_files=$(docker ps --filter label=com.docker.compose.project=ai-node \
  --format '{{index .Labels "com.docker.compose.project.config_files"}}' 2>/dev/null \
  | tr ',' '\n' | grep -v '^$' | sort -u || true)
if [[ -n $config_files ]]; then
  while IFS= read -r f; do
    [[ -f $f ]] && compose+=(-f "$f")
  done <<< "$config_files"
else
  compose+=(-f ai-node.yml)
fi
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
  rollback_running_stack || echo "ERROR: automatic rollback failed; images were restored but container DATA was not rolled back — restore it from the pre-update backup under /srv/backups/local if state is inconsistent" >&2
  exit 1
fi
if ! /srv/ai-node/scripts/wait-stack-healthy.sh; then
  rollback_running_stack || echo "ERROR: automatic rollback failed; images were restored but container DATA was not rolled back — restore it from the pre-update backup under /srv/backups/local if state is inconsistent" >&2
  exit 1
fi
echo "Unused images/build cache were not deleted automatically. Review with: docker system df"
