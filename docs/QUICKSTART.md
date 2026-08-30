# Quickstart: bare Ubuntu 24.04 to a running stack

About 15 minutes on a fresh machine, plus image build/pull time on first start.

## Prerequisites

- Ubuntu 24.04+ (Server or minimal install), with Internet access.
- `git` (`sudo apt-get install -y git`).
- Optional: an NVIDIA GPU with a working driver (`nvidia-smi`). Without one,
  Ollama and ComfyUI fall back to CPU or fail their GPU reservation; the
  installer installs `nvidia-container-toolkit` only when a GPU is detected.
- Optional but recommended: Tailscale installed and logged in. The stack binds
  ports to both the LAN and Tailscale addresses and waits for both at boot.
  If you will not use Tailscale, pass `--skip-tailscale` to the installer.

## Install

```bash
git clone <this-repository-url> homeserve
cd homeserve
sudo scripts/install.sh
```

The installer auto-detects the LAN address (confirm or override with
`--lan-ip`), renders `.env` from `.env.example`, generates
`secrets/*.env` with `scripts/bootstrap-secrets.sh`, copies the repository to
`/srv/ai-node`, installs the systemd units from `host/etc/systemd/system/`
(stack, backup service+timer, SMART-metrics service+timer), runs
`scripts/validate-config.sh --strict`, and only then enables and starts the
stack and the nightly backup timer. It is safe to re-run; existing `.env`,
secrets, and data are never overwritten.

Non-interactive example:

```bash
sudo scripts/install.sh --lan-ip 192.168.1.50 --tailscale-ip 100.x.y.z
# or, without Tailscale:
sudo scripts/install.sh --lan-ip 192.168.1.50 --skip-tailscale
```

## First look

- Open WebUI (chat with Ollama): `http://LAN_IP:3000` — authentication is on;
  see the `ENABLE_SIGNUP` comment in `compose/ai-node.yml` for creating the
  first (admin) account
- Grafana dashboards: `http://LAN_IP:3001` (admin credentials in
  `/srv/ai-node/secrets/grafana.env`)
- Every other URL: [SERVICE_MAP.md](../SERVICE_MAP.md)
- Health check: `/srv/ai-node/scripts/health-check.sh`

Pull a model before chatting: `docker exec ai-ollama ollama pull qwen3:4b`.

## Front door: Caddy proxy

The stack includes a Caddy reverse proxy on ports `80`/`443` serving every UI
as `https://<name>.homeserve.lan` (`webui`, `comfy`, `grafana`, `kuma`,
`prom`, `gateway`, `ntfy`) with certificates from its own internal CA, plus a
landing dashboard at `https://homeserve.lan`. Two one-time client-side steps,
both detailed in the header comments of [config/caddy/Caddyfile](../config/caddy/Caddyfile):

1. Make `*.homeserve.lan` resolve to the server (router dnsmasq wildcard,
   Pi-hole local DNS, or per-device `/etc/hosts` entries).
2. Trust the Caddy root CA on each device (copy it out of the `edge-caddy`
   container with `docker cp`).

Until then, the legacy per-service ports keep working unchanged.

## Alerts

Prometheus sends alerts to Alertmanager, which posts them to the self-hosted
ntfy service. To get push notifications on a phone: install the ntfy app, add
the server `http://LAN_IP:2586` (or `https://ntfy.homeserve.lan` once the
proxy is set up), and subscribe to `homeserve-alerts` — critical alerts also
go to `homeserve-alerts-critical`, which can be subscribed with max priority.
Alert states are also visible at `http://LAN_IP:9091/alerts`.

## Updating

```bash
cd /srv/ai-node && git pull
sudo scripts/install.sh   # re-applies units/config; keeps .env and secrets
/srv/ai-node/scripts/update-stack.sh
```

`update-stack.sh` validates, pulls and rebuilds images, restarts, and runs the
health check.

## Backups

`ai-node-backup.timer` runs `scripts/backup.sh` nightly around 03:30, writing
verified archives to `/srv/backups/local` (14 days retained). For real disaster
recovery, copy archives off-host or run
`sudo BACKUP_DEST=/mnt/external /srv/ai-node/scripts/backup.sh` against a
separate mounted disk.
