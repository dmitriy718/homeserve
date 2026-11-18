#!/bin/sh
set -eu
LOCAL_PORT="${LOCAL_PORT:-11434}"
REMOTE_PORT="${REMOTE_PORT:-11434}"

mkdir -p /tmp/ssh
cp /run/secrets/ollama_tunnel_key /tmp/ssh/id_ed25519
chmod 0600 /tmp/ssh/id_ed25519

exec ssh -N -T \
  -i /tmp/ssh/id_ed25519 \
  -o IdentitiesOnly=yes \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/run/secrets/ollama_tunnel_known_hosts \
  -o ServerAliveInterval=20 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  -o LogLevel=ERROR \
  -L "0.0.0.0:${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" \
  dmitr@100.103.12.38
