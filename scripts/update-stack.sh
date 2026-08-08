#!/usr/bin/env bash
set -euo pipefail
cd /srv/ai-node/compose
docker compose --env-file ../.env -f ai-node.yml config --quiet
docker compose --env-file ../.env -f ai-node.yml pull --ignore-buildable
docker compose --env-file ../.env -f ai-node.yml build --pull
docker compose --env-file ../.env -f ai-node.yml up -d --remove-orphans
/srv/ai-node/scripts/health-check.sh
echo "Unused images/build cache were not deleted automatically. Review with: docker system df"

