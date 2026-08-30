#!/usr/bin/env bash
# First-run installer for the ai-node stack on a generic Ubuntu 24.04+ host.
# Idempotent: re-running installs only missing pieces and never overwrites
# an existing .env, secrets, systemd units, or application data.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
install_dir=/srv/ai-node
lan_ip=""
tailscale_ip=""
skip_tailscale=false

usage() {
  cat <<'EOF'
Usage: sudo scripts/install.sh [OPTIONS]

Options:
  --lan-ip IP         Primary LAN address (default: auto-detect, prompt if TTY)
  --tailscale-ip IP   Tailscale address (default: auto-detect via tailscaled)
  --skip-tailscale    No Tailscale: bind TAILSCALE_IP to 127.0.0.1 instead
  --dir PATH          Install directory (default: /srv/ai-node)
  -h, --help          Show this help
EOF
}

while (($#)); do
  case $1 in
    --lan-ip) lan_ip=${2:?"--lan-ip requires a value"}; lan_ip_given=true; shift 2 ;;
    --tailscale-ip) tailscale_ip=${2:?"--tailscale-ip requires a value"}; shift 2 ;;
    --skip-tailscale) skip_tailscale=true; shift ;;
    --dir) install_dir=${2:?"--dir requires a value"}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if ((EUID != 0)); then
  echo "This installer must run as root (use sudo)." >&2
  exit 1
fi

# --- Addresses -------------------------------------------------------------

if [[ -z $lan_ip ]]; then
  lan_ip=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1)
fi
if [[ -z $lan_ip ]]; then
  echo "Could not detect the LAN address; pass --lan-ip." >&2
  exit 1
fi
if [[ -t 0 && ${lan_ip_given:-false} == false ]]; then
  read -r -p "LAN address [$lan_ip]: " answer
  lan_ip=${answer:-$lan_ip}
fi

if $skip_tailscale; then
  tailscale_ip=127.0.0.1
  echo "WARNING: --skip-tailscale set. Ports will bind to 127.0.0.1 instead of a"
  echo "WARNING: Tailscale address. Remote access requires the LAN or a later"
  echo "WARNING: Tailscale setup plus a TAILSCALE_IP update in $install_dir/.env."
elif [[ -z $tailscale_ip ]]; then
  if command -v tailscale >/dev/null; then
    tailscale_ip=$(tailscale ip -4 2>/dev/null | head -n1 || true)
  fi
  if [[ -z $tailscale_ip ]]; then
    echo "No Tailscale address found. This stack binds ports to both LAN_IP and"
    echo "TAILSCALE_IP and ai-node-stack.service waits for both at boot."
    echo "Install and log in to Tailscale first (https://tailscale.com), pass"
    echo "--tailscale-ip, or re-run with --skip-tailscale." >&2
    exit 1
  fi
fi
echo "Using LAN_IP=$lan_ip TAILSCALE_IP=$tailscale_ip"

# --- Prerequisites ---------------------------------------------------------

packages=()
command -v docker >/dev/null || packages+=(docker.io)
docker compose version >/dev/null 2>&1 || packages+=(docker-compose-v2)
for tool in git jq rsync openssl; do
  command -v "$tool" >/dev/null || packages+=("$tool")
done
if ((${#packages[@]})); then
  echo "Installing packages: ${packages[*]}"
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
fi
systemctl enable --now docker

# NVIDIA container toolkit only when an NVIDIA GPU is present.
if grep -qs '^0x10de' /sys/bus/pci/devices/*/vendor 2>/dev/null; then
  if ! command -v nvidia-smi >/dev/null; then
    echo "WARNING: NVIDIA GPU detected but no driver (nvidia-smi missing)." >&2
    echo "WARNING: Install one with 'ubuntu-drivers install' and reboot;" >&2
    echo "WARNING: ollama and comfyui need it for GPU inference." >&2
  fi
  if ! dpkg -s nvidia-container-toolkit >/dev/null 2>&1; then
    echo "Installing nvidia-container-toolkit"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
  fi
fi

# --- Install directory -----------------------------------------------------

if [[ $repo_root != "$install_dir" ]]; then
  echo "Copying repository to $install_dir"
  mkdir -p "$install_dir"
  rsync -a \
    --exclude='.git' --exclude='/.env' --exclude='/secrets' \
    --exclude='/data' --exclude='/logs' \
    --exclude='/agent-platform/workspaces' --exclude='/agent-platform/artifacts' \
    --exclude='/agent-platform/cache' --exclude='/agent-platform/logs' \
    "$repo_root/" "$install_dir/"
else
  echo "Already running from $install_dir; skipping copy"
fi
mkdir -p /srv/models/ollama /srv/models/embeddings /srv/models/comfyui "$install_dir/data"

# --- Configuration and secrets ---------------------------------------------

if [[ -f $install_dir/.env ]]; then
  echo "Keeping existing $install_dir/.env"
else
  sed -e "s/^LAN_IP=.*/LAN_IP=$lan_ip/" \
      -e "s/^TAILSCALE_IP=.*/TAILSCALE_IP=$tailscale_ip/" \
      "$install_dir/.env.example" > "$install_dir/.env"
  chmod 0600 "$install_dir/.env"
  echo "Rendered $install_dir/.env"
fi

"$install_dir/scripts/bootstrap-secrets.sh"

# --- systemd units ----------------------------------------------------------

for unit in "$install_dir"/host/etc/systemd/system/*; do
  target=/etc/systemd/system/$(basename "$unit")
  if [[ $install_dir == /srv/ai-node ]]; then
    install -m 0644 "$unit" "$target"
  else
    # Units reference /srv/ai-node; rewrite paths for a custom --dir.
    sed "s|/srv/ai-node|$install_dir|g" "$unit" > "$target"
    chmod 0644 "$target"
    echo "NOTE: scripts/wait-network-addresses.sh sources /srv/ai-node/.env;"
    echo "      with a custom --dir you must adjust that path manually."
  fi
  echo "Installed $target"
done
systemctl daemon-reload

# --- Validate, then start ----------------------------------------------------

if ! "$install_dir/scripts/validate-config.sh" --strict; then
  echo "Validation failed; the stack was NOT started. Fix the issues above" >&2
  echo "and re-run this installer (it is safe to re-run)." >&2
  exit 1
fi

systemctl enable --now ai-node-stack.service
# Enable every shipped timer (backup, smart-metrics, ...).
for timer in "$install_dir"/host/etc/systemd/system/*.timer; do
  systemctl enable --now "$(basename "$timer")"
done

cat <<EOF

Installation complete.

Next steps:
  - Watch startup:      systemctl status ai-node-stack
  - Open WebUI (chat):  http://$lan_ip:3000 (first account becomes admin;
                        see the ENABLE_SIGNUP comment in compose/ai-node.yml)
  - Front door (proxy): https://webui.homeserve.lan once DNS and CA trust are
                        set up per config/caddy/Caddyfile
  - Grafana:            http://$lan_ip:3001 (admin password in $install_dir/secrets/grafana.env)
  - Alert phone app:    subscribe to ntfy topics at http://$lan_ip:2586
                        (topics: homeserve-alerts, homeserve-alerts-critical)
  - Service URLs:       $install_dir/SERVICE_MAP.md
  - Health check:       $install_dir/scripts/health-check.sh
  - Nightly backups:    systemctl list-timers ai-node-backup.timer
EOF
