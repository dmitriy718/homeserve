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
`/srv/ai-node`, installs all 13 systemd units from `host/etc/systemd/system/`
(stack service plus backup, offsite-backup, restore-test, SMART-metrics,
battery-metrics, and update service+timer pairs), runs
`scripts/validate-config.sh --strict`, and only then enables and starts the
stack and the shipped timers. It is safe to re-run; existing `.env`,
secrets, and data are never overwritten.

Non-interactive example:

```bash
sudo scripts/install.sh --lan-ip 192.168.1.50 --tailscale-ip 100.x.y.z
# or, without Tailscale:
sudo scripts/install.sh --lan-ip 192.168.1.50 --skip-tailscale
```

## Front door: Caddy proxy

The stack includes a Caddy reverse proxy on port `443` serving every UI
as `https://<name>.homeserve.lan` (`auth`, `lldap`, `webui`, `comfy`,
`grafana`, `kuma`, `prom`, `gateway`, `ntfy`) with certificates from its own
internal CA, plus a landing dashboard at `https://homeserve.lan`. Port 80
belongs to a preserved system httpd and Caddy sets up no redirect from it —
always use the `https://` URLs directly. Two one-time client-side steps,
both detailed in the header comments of [config/caddy/Caddyfile](../config/caddy/Caddyfile):

1. Make `*.homeserve.lan` resolve to the server (router dnsmasq wildcard,
   Pi-hole local DNS, or per-device `/etc/hosts` entries).
2. Trust the Caddy root CA on each device (copy it out of the `edge-caddy`
   container with `docker cp`, then onto the client).

Do these before the first look below: Open WebUI and Grafana publish no
ports at all (proxy only), and the other `https://` URLs need them too.
Most legacy per-service ports keep working until then.

## First look

No logins anywhere by default — every UI opens directly:

- Landing dashboard: `https://homeserve.lan` — tiles for every service.
- Open WebUI (chat with Ollama): `https://webui.homeserve.lan`
- Grafana dashboards: `https://grafana.homeserve.lan`
- ComfyUI: `https://comfy.homeserve.lan` — Uptime Kuma: `https://kuma.homeserve.lan`
- Speedtest Tracker is the one exception with a login (no guest mode
  upstream): credentials in `/srv/ai-node/secrets/speedtest.env`.

The SSO stack (Authelia + LLDAP) is installed but set to bypass. To turn
logins on, follow the three steps in `config/authelia/configuration.yml`;
the LLDAP admin login is `admin` with `LLDAP_LDAP_USER_PASS` from
`/srv/ai-node/secrets/lldap.env`.
- Every other URL: [SERVICE_MAP.md](../SERVICE_MAP.md)
- Health check, on the server: `/srv/ai-node/scripts/health-check.sh`

On the server, pull a model before chatting: `docker exec ai-ollama ollama pull qwen3:4b`.

## Alerts

Prometheus sends alerts to Alertmanager, which posts them to the self-hosted
ntfy service. To get push notifications on a phone: install the ntfy app, add
the server `http://LAN_IP:2586` (or `https://ntfy.homeserve.lan` once the
proxy is set up), and subscribe to `homeserve-alerts` — critical alerts also
go to `homeserve-alerts-critical`, which can be subscribed with max priority.
Alert states are also visible at `http://LAN_IP:9091/alerts`.

## Updating

```bash
sudo /srv/ai-node/scripts/deploy.sh
```

`deploy.sh` is the primary update path: it fast-forwards the `/srv/ai-node`
git checkout, re-runs `bootstrap-secrets.sh`, re-installs changed systemd
units, validates, and then runs `update-stack.sh` (pulls and rebuilds images,
restarts, runs the health check). Preview first with `--check` or `--dry-run`.
For image-only updates without touching the checkout, run
`/srv/ai-node/scripts/update-stack.sh` directly. `deploy.sh` requires
`/srv/ai-node` to be a git clone; if `install.sh` rsynced the repository from
a clone elsewhere (no `.git`), it prints the one-time conversion commands.

## Backups

`ai-node-backup.timer` runs `scripts/backup.sh` nightly around 03:30, writing
verified archives to `/srv/backups/local` (14 days retained). For real disaster
recovery, copy archives off-host or run
`sudo BACKUP_DEST=/mnt/external /srv/ai-node/scripts/backup.sh` against a
separate mounted disk.
