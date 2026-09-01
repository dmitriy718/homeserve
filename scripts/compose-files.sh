#!/usr/bin/env bash
# Echoes the active compose file set for the ai-node stack, one path per
# line: the base compose file plus any apps/ overlay files recorded in
# container labels. Used by update-stack.sh and ai-node-stack.service so both
# build the same -f arguments for `up -d --remove-orphans`.
#
# `docker ps -a` includes stopped containers because labels persist on them —
# an apps/ overlay container that is currently stopped still keeps its -f
# file, otherwise `up -d --remove-orphans` would delete it. Falls back to
# the base file only.
set -euo pipefail

config_files=$(docker ps -a --filter label=com.docker.compose.project=ai-node \
  --format '{{index .Labels "com.docker.compose.project.config_files"}}' 2>/dev/null \
  | tr ',' '\n' | grep -v '^$' | sort -u || true)
files=()
if [[ -n $config_files ]]; then
  while IFS= read -r f; do
    [[ -f $f ]] && files+=("$f")
  done <<< "$config_files"
fi
if ((${#files[@]} == 0)); then
  files=(/srv/ai-node/compose/ai-node.yml)
fi
printf '%s\n' "${files[@]}"
