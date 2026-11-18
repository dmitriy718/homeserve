# Service Map — `homeserv` (`ai-node`)

- **LAN Address:** `192.168.0.148`
- **Tailscale Address:** `100.65.105.46`
- **GPU:** NVIDIA GeForce RTX 5060 Laptop GPU (`8151 MiB` VRAM, Driver `595.99.02`)

---

## 1. Front Door (`edge-caddy` HTTPS Reverse Proxy)

Caddy (`caddy:2.11.4-alpine`) publishes TCP/UDP `443` on both `192.168.0.148` and `100.65.105.46` and serves all web UIs on subdomains of `BASE_DOMAIN` (default `homeserve.lan`) with automatic internal TLS. See `config/caddy/Caddyfile` for DNS and client CA-trust setup.

Authelia (`auth-authelia`) enforces `one_factor` SSO on `https://webui.homeserve.lan` and defaults to `bypass` on the remaining trusted-LAN subdomains (`config/authelia/configuration.yml`).

| Subdomain URL | Upstream Target | Access Policy | Description |
|---|---|---|---|
| `https://homeserve.lan` | Static (`services/dashboard/`) | `bypass` (LAN/Tailscale) | Landing dashboard with real-time service health dots |
| `https://webui.homeserve.lan` | `ai-open-webui:8080` | `one_factor` (Authelia SSO) | Open WebUI (`v0.11.3`) chat & coding agent workspace |
| `https://comfy.homeserve.lan` | `ai-comfyui:8188` | `bypass` (LAN/Tailscale) | ComfyUI node workflow studio & Site Host Hub |
| `https://grafana.homeserve.lan` | `monitor-grafana:3000` | `bypass` (LAN/Tailscale) | Grafana (`13.2.1`) provisioned host, GPU & backup dashboards |
| `https://kuma.homeserve.lan` | `monitor-uptime-kuma:3001` | `bypass` (LAN/Tailscale) | Uptime Kuma (`2.5.3`) synthetic monitor |
| `https://prom.homeserve.lan` | `monitor-prometheus:9090` | `bypass` (LAN/Tailscale) | Prometheus (`v3.14.0`) query UI & alert evaluation |
| `https://gateway.homeserve.lan` | `ai-agent-gateway:8090` | Bearer `X-Agent-Key` | Agent Gateway OpenAPI tool server |
| `https://ntfy.homeserve.lan` | `monitor-ntfy:80` | Open topic pub/sub | Self-hosted ntfy (`v2.28.0`) push notifications |
| `https://auth.homeserve.lan` | `auth-authelia:9091` | Public portal | Authelia (`4.39.22`) SSO login portal |
| `https://lldap.homeserve.lan` | `auth-lldap:17170` | `bypass` / Admin login | LLDAP (`v0.6.3-alpine`) LDAP user management UI |

---

## 2. Core Docker Compose Services (`compose/ai-node.yml`)

| Service | Container | Published Ports | LAN Endpoint | Tailscale Endpoint | Persistent Data | GPU | Health Check |
|---|---|---|---|---|---|---|---|
| **Caddy** | `edge-caddy` | `443/tcp`, `443/udp` | `https://192.168.0.148` | `https://100.65.105.46` | `/srv/ai-node/data/caddy` | No | Admin API `:2019` |
| **Ollama** | `ai-ollama` | `11434` (loopback, LAN, TS) | `http://192.168.0.148:11434` | `http://100.65.105.46:11434` | `/srv/ai-node/data/ollama` | RTX 5060 | `ollama ps` / `/api/tags` |
| **Open WebUI** | `ai-open-webui` | Proxy-only (`8080` internal) | `https://webui.homeserve.lan` | `https://webui.homeserve.lan` | `/srv/ai-node/data/open-webui` | Via Ollama | `/health` |
| **Embeddings** | `ai-embeddings` | `8081 -> 8080` | `http://192.168.0.148:8081` | `http://100.65.105.46:8081` | Stateless (uses `ai-ollama` `all-minilm`) | Via Ollama | `/health` |
| **ComfyUI** | `ai-comfyui` | `8188` | `http://192.168.0.148:8188` | `http://100.65.105.46:8188` | `/srv/ai-node/data/comfyui` | RTX 5060 (`6g` cap) | `/system_stats` |
| **Agent Gateway** | `ai-agent-gateway` | `8090` | `http://192.168.0.148:8090` | `http://100.65.105.46:8090` | `/srv/ai-node/agent-platform` | No | `/health` |
| **Agent Shell** | `ai-agent-shell` | `8091` internal (`agent-exec`) | Internal only | Internal only | `/srv/ai-node/agent-platform/{workspaces,cache}` | No | `/health` |
| **Agent Host** | `ai-agent-host` | `8092` internal (`agent-host`) | Internal only | Internal only | Host `/` (`rshared`) via `nsenter` | No | `/health` |
| **GPU Scheduler** | `ai-gpu-scheduler` | `127.0.0.1:8077` | Loopback only | Not exposed | In-memory lease table | No | `/state` |
| **Prometheus** | `monitor-prometheus` | `9091 -> 9090` | `http://192.168.0.148:9091` | `http://100.65.105.46:9091` | `/srv/ai-node/data/prometheus` | No | `/-/ready` |
| **Alertmanager** | `monitor-alertmanager` | `9093` internal | Internal only | Internal only | `/srv/ai-node/data/alertmanager` | No | `/-/healthy` |
| **ntfy** | `monitor-ntfy` | `2586 -> 80` | `http://192.168.0.148:2586` | `http://100.65.105.46:2586` | `/srv/ai-node/data/ntfy` | No | `/v1/health` |
| **Grafana** | `monitor-grafana` | Proxy-only (`3000` internal) | `https://grafana.homeserve.lan` | `https://grafana.homeserve.lan` | `/srv/ai-node/data/grafana` | No | `/api/health` |
| **Uptime Kuma** | `monitor-uptime-kuma` | `3002 -> 3001` | `http://192.168.0.148:3002` | `http://100.65.105.46:3002` | `/srv/ai-node/data/uptime-kuma` | No | `/api/entry-page` |
| **Speedtest** | `monitor-speedtest` | `8765 -> 80` | `http://192.168.0.148:8765` | `http://100.65.105.46:8765` | `/srv/ai-node/data/speedtest` | No | `/api/healthcheck` |
| **Node Exporter** | `monitor-node-exporter` | `9100` internal | Internal only | Internal only | Host `/proc`, `/sys`, textfile collector | No | `/metrics` |
| **NVIDIA Exporter** | `monitor-nvidia-exporter` | `9400` internal | Internal only | Internal only | None (`nvidia-smi` telemetry) | Yes | `/metrics` |
| **Blackbox Exporter** | `monitor-blackbox` | `9115` internal | Internal only | Internal only | None | No | `/-/healthy` |
| **Authelia** | `auth-authelia` | `9091` internal | Internal only | Internal only | `/srv/ai-node/data/authelia` | No | `/api/health` |
| **LLDAP** | `auth-lldap` | `17170`, `3890` internal | Internal only | Internal only | `/srv/ai-node/data/lldap` | No | `/` |

---

## 3. Host User Systemd Daemons & Companion Containers

Managed under `dima` user systemd (`systemctl --user`) and monitored every 15 minutes by `macmini-ops` fleet watchdog:

| Unit / Container | Type | Working Directory / Image | Purpose |
|---|---|---|---|
| `homeserv-agent-fleet.service` | User systemd service | `/srv/ai-node/services/agent-fleet` | Runs `fleet_supervisor.py` (3 Marketing, 3 Maintenance, 3 Cleanup agents + RTX 5060 GPU render queue) |
| `para-enterprise.service` | User systemd service | `/home/dima/services/enterprise` | Autonomous SEO/GEO, backlink & revenue governance daemon |
| `answered.service` | User systemd service | `/home/dima/services/answered` | Answered autonomous worker daemon |
| `gighound-growth.service` | User systemd service | `/home/dima/gighound/growth` | GigHound contract acquisition & growth daemon (`--interval 900`) |
| `para-commander.timer` | User systemd timer | `/home/dima/services/enterprise` | Periodic Para Commander orchestration |
| `para-agent-a0.timer` | User systemd timer | `/home/dima/services/enterprise` | Periodic Agent A0 health & funnel sweep |
| `para-fleet-sync.timer` | User systemd timer | `/home/dima/services/enterprise` | Periodic multi-node state sync |
| `steward-steward-1` | Docker container | `steward-steward` | Steward background worker container |
| `sentinel-*` (`api`, `worker`, `watchdog`, `inference`, `nginx`, `redis`) | Docker Compose stack | `sentinel-core:2.3.0` | Sentinel core API (`:8000`) & TLS proxy (`:8443`) |

---

## 4. Optional Compose Overlays (`apps/`)

Opt-in Compose overlays (not started by default; enable via `docker compose --env-file .env -f compose/ai-node.yml -f apps/<name>.yml up -d`):

| App | Purpose | Overlay File | Legacy Port | LAN URL | Subdomain | Persistent Data |
|---|---|---|---:|---|---|---|
| **Jellyfin** | Media server | `apps/jellyfin.yml` | `8096` | `http://192.168.0.148:8096` | `https://jellyfin.homeserve.lan` | `/srv/ai-node/data/jellyfin` |
| **Immich** | Photo & video backup | `apps/immich.yml` | `2283` | `http://192.168.0.148:2283` | `https://immich.homeserve.lan` | `/srv/ai-node/data/immich` |
| **Nextcloud** | Files, calendar, contacts | `apps/nextcloud.yml` | `8480` | `http://192.168.0.148:8480` | `https://cloud.homeserve.lan` | `/srv/ai-node/data/nextcloud` |
