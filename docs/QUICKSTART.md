# Quickstart — Fresh Host Installation

One command takes a fresh Ubuntu 24.04+ server to a running `homeserv` AI node stack.

## 1. Prerequisites

- Ubuntu 24.04+ (x86_64) with root (`sudo`) access
- NVIDIA GPU + drivers (for `ai-ollama`, `ai-comfyui`, and `monitor-nvidia-exporter`)
- Network connectivity (LAN + Tailscale recommended)

## 2. Clone & Install

```bash
sudo mkdir -p /srv/ai-node
sudo chown "$USER:$USER" /srv/ai-node
git clone https://github.com/dmitriy718/homeserve.git /srv/ai-node
cd /srv/ai-node
sudo /srv/ai-node/scripts/install.sh
```

`install.sh` is idempotent and performs the following steps:
1. Installs Docker Engine, Compose plugin, NVIDIA Container Toolkit, UFW, Restic, and host utilities.
2. Detects `LAN_IP` (e.g., `192.168.0.148`) and `TAILSCALE_IP` (e.g., `100.65.105.46`) and writes `/srv/ai-node/.env`.
3. Runs `scripts/bootstrap-secrets.sh` to generate local credentials under `/srv/ai-node/secrets/` (`0600`).
4. Installs and enables systemd units (`ai-node-stack.service`, `ai-node-backup.timer`, `ai-node-offsite-backup.timer`, `ai-node-restore-test.timer`, `ai-node-battery-metrics.timer`).
5. Pulls and builds all Docker images, starts `compose/ai-node.yml`, and runs `scripts/health-check.sh`.

## 3. Pull Default Ollama Models

```bash
docker exec ai-ollama ollama pull qwen3:8b
docker exec ai-ollama ollama pull all-minilm:latest
docker exec ai-ollama ollama pull moondream:latest
```

## 4. Trust the Internal TLS Certificate & Set Up Local DNS

`edge-caddy` serves all UIs over HTTPS on `*.homeserve.lan` (port `443`).
1. Point `homeserve.lan` and `*.homeserve.lan` (`webui`, `comfy`, `grafana`, `kuma`, `prom`, `gateway`, `ntfy`, `auth`, `lldap`) to `192.168.0.148` (or `100.65.105.46`) in your local DNS resolver or `/etc/hosts`.
2. Copy the Caddy internal root CA certificate from `edge-caddy` and trust it on your client machine:
   ```bash
   docker cp edge-caddy:/data/caddy/pki/authorities/local/root.crt ./homeserv-caddy-root.crt
   ```

## 5. First Look

- **Landing Dashboard:** `https://homeserve.lan`
- **Open WebUI (Authelia SSO):** `https://webui.homeserve.lan` (log in via Authelia; initial LLDAP admin password is in `/srv/ai-node/secrets/lldap.env`)
- **ComfyUI Studio:** `https://comfy.homeserve.lan` (or `http://192.168.0.148:8188`)
- **Grafana Dashboards:** `https://grafana.homeserve.lan`
- **Uptime Kuma:** `https://kuma.homeserve.lan` (or `http://192.168.0.148:3002`)

For complete day-to-day operational guides, coding agent workflows, GPU scheduling, and backup/restore procedures, see **[docs/HOWTO.md](HOWTO.md)**.
