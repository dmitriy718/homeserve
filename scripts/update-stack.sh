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
docker compose --env-file ../.env -f ai-node.yml pull --ignore-buildable
docker compose --env-file ../.env -f ai-node.yml build --pull
docker compose --env-file ../.env -f ai-node.yml config --quiet
docker compose --env-file ../.env -f ai-node.yml up -d --remove-orphans
/srv/ai-node/scripts/wait-stack-healthy.sh
echo "Unused images/build cache were not deleted automatically. Review with: docker system df"
