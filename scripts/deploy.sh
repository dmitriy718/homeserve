#!/usr/bin/env bash
# Safe self-update of the deployed checkout and the stack.
#
# Assumption: /srv/ai-node is a git clone of this repository. Git is the only
# sync mechanism used here — see the rsync --delete warning in
# docs/PROVISIONING_NOTES.md; application data lives below the same tree, so
# this script never modifies the checkout except through git itself.
#
# Hosts installed by scripts/install.sh from a clone located elsewhere have
# NO .git at /srv/ai-node (install.sh rsyncs with --exclude='.git'). This
# script detects that case and prints conversion guidance instead of guessing.
set -euo pipefail

if ((EUID != 0)); then
  exec sudo -- "$0" "$@"
fi

# A git pull can replace this script mid-run and bash reads scripts lazily,
# so execute from a private copy.
if [[ -z ${AI_NODE_DEPLOY_REEXEC:-} ]]; then
  self_copy=$(mktemp /tmp/.ai-node-deploy.XXXXXX)
  cp "${BASH_SOURCE[0]}" "$self_copy"
  chmod 0700 "$self_copy"
  AI_NODE_DEPLOY_REEXEC=1 AI_NODE_DEPLOY_SELF=$(readlink -f "${BASH_SOURCE[0]}") \
    exec bash "$self_copy" "$@"
fi
trap 'rm -f "${BASH_SOURCE[0]}"' EXIT
self_name=${AI_NODE_DEPLOY_SELF:-scripts/deploy.sh}

checkout=${AI_NODE_CHECKOUT:-/srv/ai-node}

usage() {
  cat <<EOF
Usage: sudo scripts/deploy.sh [--check | --dry-run] [--force]

Fast-forward the $checkout git checkout, re-apply secrets scaffolding and
changed systemd units, validate the configuration, and run
scripts/update-stack.sh to pull/build/restart with its rollback safety.

Options:
  --check    Report behind/ahead/dirty status and exit (no mutations)
  --dry-run  Fetch and show what would change; no mutations
  --force    Proceed even if the checkout has uncommitted changes
  -h, --help Show this help

AI_NODE_CHECKOUT overrides the checkout path (default /srv/ai-node).
EOF
}

dry_run=false
check=false
force=false
for arg in "$@"; do
  case $arg in
    --check) check=true ;;
    --dry-run) dry_run=true ;;
    --force) force=true ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
if $check && $dry_run; then
  echo "--check and --dry-run are mutually exclusive" >&2
  exit 2
fi

# Wrong-machine guard: this script installs and enables systemd units in
# /etc/systemd/system and manages the stack, so refuse to run anywhere but
# the ai-node host unless explicitly overridden.
if [[ ! -d $checkout/.git && ${AI_NODE_ON_SERVER:-} != 1 ]]; then
  echo "must run on the ai-node host (or set AI_NODE_ON_SERVER=1)" >&2
  exit 1
fi

git=(git -c safe.directory="$checkout" -C "$checkout")

if [[ ! -d $checkout/.git ]]; then
  cat >&2 <<EOF
ERROR: $checkout is not a git checkout (no .git directory).
scripts/install.sh rsyncs this repository into place and excludes .git, so
hosts installed that way cannot be self-updated by this script. To convert
the deployment into a clone, run:

  sudo git -C $checkout init
  sudo git -C $checkout remote add origin <repository-url>
  sudo git -C $checkout fetch origin
  sudo git -C $checkout checkout -b <branch> --track origin/<branch>

The checkout only writes tracked files; .env, secrets/, and data/ are
git-ignored and are left alone. Then re-run: $self_name
EOF
  exit 1
fi

echo "Fetching origin..."
"${git[@]}" fetch origin

if ! upstream=$("${git[@]}" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null); then
  echo "ERROR: the current branch has no upstream configured." >&2
  echo "Set one with: git -C $checkout branch --set-upstream-to=origin/<branch>" >&2
  exit 1
fi
branch=$("${git[@]}" rev-parse --abbrev-ref HEAD)
behind=$("${git[@]}" rev-list --count "HEAD..$upstream")
ahead=$("${git[@]}" rev-list --count "$upstream..HEAD")

dirty=()
untracked=()
while IFS= read -r line; do
  if [[ $line == '?? '* ]]; then
    untracked+=("${line:3}")
  else
    dirty+=("$line")
  fi
done < <("${git[@]}" status --porcelain)

echo "checkout: $checkout (branch $branch, upstream $upstream)"
echo "behind:   $behind commit(s)"
echo "ahead:    $ahead commit(s)"
if ((${#dirty[@]})); then
  echo "dirty:    ${#dirty[@]} modified tracked file(s)"
else
  echo "dirty:    no (tracked files clean)"
fi
if ((${#untracked[@]})); then
  echo "note: ${#untracked[@]} untracked file(s) present (not blocking; ignored files such as .env and .auto-update are expected)"
fi
$check && exit 0

if ((ahead > 0)); then
  if ((behind > 0)); then
    echo "ERROR: $branch has diverged from $upstream ($ahead ahead, $behind behind)." >&2
  else
    echo "ERROR: $branch has $ahead local commit(s) not on $upstream." >&2
  fi
  echo "Review them with: git -C $checkout log --oneline $upstream..HEAD" >&2
  echo "Either push them to origin, or discard them with:" >&2
  echo "  git -C $checkout reset --hard $upstream" >&2
  echo "This script only fast-forwards; resolve the divergence manually." >&2
  exit 1
fi

if ((${#dirty[@]})) && ! $force; then
  echo "ERROR: $checkout has uncommitted changes:" >&2
  printf '  %s\n' "${dirty[@]}" >&2
  echo "Commit, stash, or discard them first, or re-run with --force." >&2
  exit 1
fi

if ((behind == 0)); then
  echo "$checkout is already up to date with $upstream."
  pulled=false
else
  if $dry_run; then
    echo
    echo "Would fast-forward $branch by $behind commit(s):"
    "${git[@]}" log --oneline "HEAD..$upstream"
    echo
    "${git[@]}" diff --stat "HEAD..$upstream"
    changed_units=$("${git[@]}" diff --name-only "HEAD..$upstream" -- host/etc/systemd/system/)
    if [[ -n $changed_units ]]; then
      echo
      echo "Systemd units that would be re-installed (plus daemon-reload):"
      echo "$changed_units"
    fi
    echo
    echo "Would then run: bootstrap-secrets.sh, validate-config.sh --strict, update-stack.sh"
    exit 0
  fi

  "${git[@]}" pull --ff-only
  pulled=true
fi

# Single-file bind mounts pin the inode captured at container start; a git
# pull replaces the file (new inode), leaving running containers reading the
# OLD config. Force-recreate the affected services when these files changed.
declare -A mounted_configs=(
  [config/caddy/Caddyfile]=caddy
  [monitoring/prometheus.yml]=prometheus
  [monitoring/alerts.yml]=prometheus
  [monitoring/alertmanager.yml]=alertmanager
  [config/authelia/configuration.yml]=authelia
)
recreate=()
if $pulled; then
  for cfg in "${!mounted_configs[@]}"; do
    if [[ -n $("${git[@]}" diff --name-only 'HEAD@{1}..HEAD' -- "$cfg") ]]; then
      recreate+=("${mounted_configs[$cfg]}")
    fi
  done
fi

# Idempotent: generates only secret types that do not exist yet, so newly
# added secrets from the pull are picked up without touching existing ones.
"$checkout/scripts/bootstrap-secrets.sh"

# Re-install only the systemd units that differ from /etc/systemd/system.
# Mirrors scripts/install.sh's install step, minus its custom --dir rewrite
# (this script only supports the standard /srv/ai-node layout).
changed_units=()
new_timers=()
for unit in "$checkout"/host/etc/systemd/system/*; do
  base=$(basename "$unit")
  target=/etc/systemd/system/$base
  if [[ ! -e $target ]]; then
    install -m 0644 "$unit" "$target"
    changed_units+=("$base")
    if [[ $base == *.timer ]]; then
      new_timers+=("$base")
    fi
  elif ! cmp -s "$unit" "$target"; then
    install -m 0644 "$unit" "$target"
    changed_units+=("$base")
  fi
done
if ((${#changed_units[@]})); then
  systemctl daemon-reload
  echo "Installed updated systemd units: ${changed_units[*]}"
  if ((${#new_timers[@]})); then
    systemctl enable --now "${new_timers[@]}"
    echo "Enabled new timers: ${new_timers[*]}"
  fi
else
  echo "Systemd units unchanged"
fi

"$checkout/scripts/validate-config.sh" --strict
if $pulled || ((${#changed_units[@]})); then
  "$checkout/scripts/update-stack.sh"
else
  echo "Nothing changed; for image-only stack updates, run: $checkout/scripts/update-stack.sh"
fi

if ((${#recreate[@]})); then
  mapfile -t recreate < <(printf '%s\n' "${recreate[@]}" | sort -u)
  echo "Force-recreating services whose bind-mounted config changed: ${recreate[*]}"
  (cd "$checkout/compose" && docker compose --env-file ../.env -f ai-node.yml up -d --force-recreate "${recreate[@]}")
fi
