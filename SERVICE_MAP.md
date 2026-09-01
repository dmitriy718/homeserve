# Service map

LAN address: `192.168.1.68`  
Tailscale address: `100.65.105.46`

## Front door (Caddy proxy)

Caddy publishes `80` (redirect only) and `443` on both addresses and serves
every UI on a subdomain of `BASE_DOMAIN` (default `homeserve.lan`) with
automatic internal TLS. See `config/caddy/Caddyfile` for DNS and CA-trust
setup. The per-service ports below remain published as legacy direct access
(and bypass SSO). All subdomains except `gateway.` and `ntfy.` sit behind
Authelia single sign-on (Caddy `forward_auth`); log in once at
`https://auth.homeserve.lan`.

| URL | Service |
|---|---|
| `https://auth.homeserve.lan` | Authelia SSO portal (login page) |
| `https://lldap.homeserve.lan` | LLDAP user management (behind SSO) |
| `https://homeserve.lan` | Landing dashboard (static, from `services/dashboard/`) |
| `https://webui.homeserve.lan` | Open WebUI |
| `https://comfy.homeserve.lan` | ComfyUI |
| `https://grafana.homeserve.lan` | Grafana |
| `https://kuma.homeserve.lan` | Uptime Kuma |
| `https://prom.homeserve.lan` | Prometheus |
| `https://gateway.homeserve.lan` | Agent Gateway (API, bearer-key auth, no SSO) |
| `https://ntfy.homeserve.lan` | ntfy (no SSO; phone-app webhooks) |

## Services and legacy ports

| Service | Purpose | Container | Port | LAN URL | Tailscale URL | Persistent Data | GPU | Health Check |
|---|---|---|---:|---|---|---|---|---|
| Caddy | Edge proxy, internal TLS, landing dashboard | `edge-caddy` | 443 | `https://192.168.1.68` | `https://100.65.105.46` | `/srv/ai-node/data/caddy` | No | admin API `:2019` internally; no `:80` (system httpd owns it) |
| Ollama | LLM inference API | `ai-ollama` | 11434 | `http://192.168.1.68:11434` | `http://100.65.105.46:11434` | `/srv/models/ollama` | Yes | `/api/tags` |
| Open WebUI | Ollama chat UI | `ai-open-webui` | 3000 | `http://192.168.1.68:3000` | `http://100.65.105.46:3000` | `/srv/ai-node/data/open-webui` | Via Ollama | `/health` |
| Embeddings | MiniLM OpenAI-compatible embeddings | `ai-embeddings` | 8081 | `http://192.168.1.68:8081` | `http://100.65.105.46:8081` | `/srv/models/embeddings` | No (CPU) | `/health` |
| ComfyUI | Image workflow UI/API | `ai-comfyui` | 8188 | `http://192.168.1.68:8188` | `http://100.65.105.46:8188` | `/srv/models/comfyui`, `/srv/ai-node/data/comfyui` | Yes | `/system_stats` |
| Agent Gateway | Scoped tool API for agent jobs | `ai-agent-gateway` | 8090 | `http://192.168.1.68:8090` | `http://100.65.105.46:8090` | `/srv/ai-node/agent-platform` | No | `/health` |
| GPU Scheduler | Cooperative GPU lease arbiter | `ai-gpu-scheduler` | 8077 (loopback only) | `http://127.0.0.1:8077` (host only) | Not exposed | None (in-memory) | No | `/state` |
| Prometheus | Metrics and network-probe history | `monitor-prometheus` | 9091 | `http://192.168.1.68:9091` | `http://100.65.105.46:9091` | `/srv/ai-node/data/prometheus` | No | `/-/ready` |
| Alertmanager | Alert routing to ntfy (internal only) | `monitor-alertmanager` | 9093 internal | Not exposed | Not exposed | `/srv/ai-node/data/alertmanager` | No | `/-/healthy` internally |
| ntfy | Push notifications for alerts | `monitor-ntfy` | 2586 | `http://192.168.1.68:2586` | `http://100.65.105.46:2586` | `/srv/ai-node/data/ntfy` | No | `/v1/health` |
| Grafana | Provisioned dashboards | `monitor-grafana` | 3001 | `http://192.168.1.68:3001` | `http://100.65.105.46:3001` | `/srv/ai-node/data/grafana` | No | `/api/health` |
| Node Exporter | Host metrics (internal only) | `monitor-node-exporter` | 9100 internal | Not exposed | Not exposed | None | No | `/metrics` internally |
| NVIDIA Exporter | GPU utilization/VRAM/temp/power (internal only) | `monitor-nvidia-exporter` | 9400 internal | Not exposed | Not exposed | None | Yes | `/metrics` internally |
| Blackbox Exporter | ICMP, DNS, and HTTP probes (internal only) | `monitor-blackbox` | 9115 internal | Not exposed | Not exposed | None | No | Prometheus targets |
| Uptime Kuma | User-managed uptime UI | `monitor-uptime-kuma` | 3002 | `http://192.168.1.68:3002` | `http://100.65.105.46:3002` | `/srv/ai-node/data/uptime-kuma` | No | `/` |
| Authelia | SSO portal for the Caddy front door (internal only) | `auth-authelia` | 9091 internal | Not exposed | Not exposed | `/srv/ai-node/data/authelia` | No | `/api/health` internally |
| LLDAP | LDAP user backend for SSO (internal only) | `auth-lldap` | 17170, 3890 internal | Not exposed | Not exposed | `/srv/ai-node/data/lldap` | No | `/` internally |
| Speedtest Tracker | Daily Internet performance history | `monitor-speedtest` | 8765 | `http://192.168.1.68:8765` | `http://100.65.105.46:8765` | `/srv/ai-node/data/speedtest` | No | `/` |
| Playwright | Disposable browser verification | profile-only `dev-playwright-test` | None | Not exposed | Not exposed | Image/config only | No | `test.js` exit status |

Prometheus alert states are visible at `http://192.168.1.68:9091/alerts` (or
`https://prom.homeserve.lan/alerts`). Alerts are delivered by Alertmanager to
the self-hosted ntfy service: subscribe with the ntfy app or
`curl -N http://192.168.1.68:2586/homeserve-alerts` (critical alerts also go
to the `homeserve-alerts-critical` topic).

The pre-existing Nextcloud, Wekan, and Prometheus-snap workloads were preserved and are not managed by this Compose project.

## Optional apps (`apps/` overlays)

Curated, opt-in compose overlays — **not installed or started by default**,
and nothing in the base stack depends on them. Enable one by merging its file
into the compose command (see [docs/APPS.md](docs/APPS.md)):

```bash
docker compose --env-file .env -f compose/ai-node.yml -f apps/jellyfin.yml up -d
```

Each overlay carries the full `homeserv.*` label contract, so dashboard
tiles, Prometheus probes, health checks, and backup pauses pick it up
automatically once it runs. The Caddy subdomain routes are opt-in too —
the site block must be added to `config/caddy/Caddyfile` per app (exact
blocks in docs/APPS.md).

| App | Purpose | Overlay | Port | LAN URL | Subdomain (once routed) | Persistent Data |
|---|---|---|---:|---|---|---|
| Jellyfin | Media streaming | `apps/jellyfin.yml` | 8096 | `http://192.168.1.68:8096` | `https://jellyfin.homeserve.lan` | `/srv/ai-node/data/jellyfin`, media read-only from `MEDIA_ROOT` |
| Immich | Photo & video backup | `apps/immich.yml` | 2283 | `http://192.168.1.68:2283` | `https://immich.homeserve.lan` | `/srv/ai-node/data/immich` |
| Nextcloud | Files, calendar, contacts | `apps/nextcloud.yml` | 8480 | `http://192.168.1.68:8480` | `https://cloud.homeserve.lan` | `/srv/ai-node/data/nextcloud` |

Combined memory caps of all three apps are ~10 GiB on a 16 GB host already
running the base stack — see the resource warning in docs/APPS.md before
enabling all three at once.
