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

# LLDAP admin credentials. LLDAP_LDAP_USER_PASS is both the password for the
# "admin" login of the LLDAP UI (https://lldap.BASE_DOMAIN) and the password
# Authelia uses to bind to LDAP (see the bind secret further down).
ensure_secret "$secrets_dir/lldap.env" <<EOF
LLDAP_JWT_SECRET=$(rand_hex 32)
LLDAP_LDAP_USER_PASS=$(rand_b64 24)
EOF

# Authelia session cookie secret (Docker secret file). compose/ai-node.yml
# mounts it at /run/secrets/authelia_session_secret and points
# AUTHELIA_SESSION_SECRET_FILE at it.
ensure_secret "$secrets_dir/authelia-session.secret" <<EOF
$(rand_hex 64)
EOF

# Authelia storage encryption key (Docker secret file;
# AUTHELIA_STORAGE_ENCRYPTION_KEY_FILE). Never change it after first start:
# it encrypts data in the Authelia database.
ensure_secret "$secrets_dir/authelia-storage.secret" <<EOF
$(rand_hex 64)
EOF

# LDAP bind password for Authelia (Docker secret file;
# AUTHELIA_AUTHENTICATION_BACKEND_LDAP_PASSWORD_FILE). Must equal
# LLDAP_LDAP_USER_PASS in secrets/lldap.env, so read the value back from that
# file instead of rolling a new one — this keeps the two in sync even when
# lldap.env predates this run of the script.
lldap_user_pass=$(sed -n 's/^LLDAP_LDAP_USER_PASS=//p' "$secrets_dir/lldap.env" | head -n1)
if [[ -z $lldap_user_pass ]]; then
  echo "ERROR: secrets/lldap.env has no LLDAP_LDAP_USER_PASS; fix or delete it and re-run." >&2
  exit 1
fi
ensure_secret "$secrets_dir/authelia-ldap-bind.secret" <<EOF
$lldap_user_pass
EOF

echo "Done: $created file(s) created, existing files left untouched."
