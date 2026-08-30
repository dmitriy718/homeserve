#!/usr/bin/env bash
# Generates any missing secrets/*.env files with random, policy-compliant
# values. Idempotent: existing non-empty files are never overwritten.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
secrets_dir="$repo_root/secrets"
mkdir -p "$secrets_dir"
chmod 0700 "$secrets_dir"

rand_hex() {
  if command -v openssl >/dev/null; then
    openssl rand -hex "$1"
  else
    head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'
    echo
  fi
}

rand_b64() {
  if command -v openssl >/dev/null; then
    openssl rand -base64 "$1"
  else
    head -c "$1" /dev/urandom | base64 | tr -d '\n'
    echo
  fi
}

created=0
# Reads the desired file content on stdin; writes it only if the target is
# absent or empty, with mode 0600.
ensure_secret() {
  local path=$1
  if [[ -s $path ]]; then
    echo "KEEP   ${path#"$repo_root"/} (already exists)"
    return
  fi
  local tmp
  tmp=$(mktemp "$secrets_dir/.bootstrap.XXXXXX")
  cat >"$tmp"
  chmod 0600 "$tmp"
  mv "$tmp" "$path"
  echo "CREATE ${path#"$repo_root"/}"
  created=$((created + 1))
}

# Agent gateway API key; app.py and validate-config.sh --strict require
# at least 32 characters. Kept for the app.py env-var fallback and for
# validate-config.sh; the stack itself uses the key file below.
ensure_secret "$secrets_dir/agent-gateway.env" <<EOF
AGENT_GATEWAY_KEY=$(rand_hex 32)
EOF

# Agent gateway API key as a Docker secret file (preferred). compose/ai-node.yml
# mounts it at /run/secrets/agent_gateway_key via AGENT_GATEWAY_KEY_FILE.
ensure_secret "$secrets_dir/agent-gateway.key" <<EOF
$(rand_hex 32)
EOF

# Grafana initial admin credentials.
ensure_secret "$secrets_dir/grafana.env" <<EOF
GF_SECURITY_ADMIN_USER=admin
GF_SECURITY_ADMIN_PASSWORD=$(rand_b64 24)
EOF

# Speedtest Tracker Laravel APP_KEY: "base64:" + base64-encoded 32 random bytes.
ensure_secret "$secrets_dir/speedtest.env" <<EOF
APP_KEY=base64:$(rand_b64 32)
EOF

echo "Done: $created file(s) created, existing files left untouched."
