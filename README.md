# homeserv AI Node (`homeserve`)

`homeserv` is an Ubuntu 26.04 headless server equipped with an **NVIDIA GeForce RTX 5060 Laptop GPU (8 GiB VRAM)** providing local LLM & vision inference, 384-dimensional vector embeddings, ComfyUI image generation, a 3-tier sandboxed Coding Agent Gateway, a 24/7 Autonomous 9-Agent Fleet Supervisor, Prometheus/Grafana/Uptime Kuma/ntfy observability, and encrypted local + offsite backups.

- **Step-by-Step Operator & Developer How-To:** [docs/HOWTO.md](docs/HOWTO.md)
- **Fresh Host Installation Walkthrough:** [docs/QUICKSTART.md](docs/QUICKSTART.md)
- **Complete Port, Subdomain & Service Reference:** [SERVICE_MAP.md](SERVICE_MAP.md)
- **Open WebUI Coding Agent Guide:** [docs/OPEN_WEBUI_CODING_AGENT.md](docs/OPEN_WEBUI_CODING_AGENT.md)
- **Disaster Recovery Runbook:** [docs/DISASTER_RECOVERY.md](docs/DISASTER_RECOVERY.md)

---

## Quickstart (New Hosts)

On a fresh Ubuntu 24.04+ machine, clone this repository to `/srv/ai-node` and run:

```bash
sudo /srv/ai-node/scripts/install.sh
```

It installs prerequisites, renders `.env`, generates secrets in `/srv/ai-node/secrets`, installs systemd units, validates the Compose stack, and starts all services. See [docs/QUICKSTART.md](docs/QUICKSTART.md) for the full first-boot walkthrough.

---

## Access & Network Boundary

- **LAN Address:** `192.168.0.148` — `ssh dima@192.168.0.148` or `ssh homeserv`
- **Tailscale Address:** `100.65.105.46` — `ssh dima@100.65.105.46` (standard OpenSSH key authentication with Tailscale SSH interception disabled via `sudo tailscale set --ssh=false --operator=dima`)
- **Front-Door HTTPS Proxy (`edge-caddy`):** Publishes `443` on both `192.168.0.148` and `100.65.105.46`, serving every UI with automatic internal TLS on subdomains of `BASE_DOMAIN` (default `homeserve.lan`):
  - `https://homeserve.lan` — Static landing dashboard with live health indicators
  - `https://webui.homeserve.lan` — Open WebUI (`v0.11.3`, protected by Authelia `one_factor` SSO)
  - `https://comfy.homeserve.lan` — ComfyUI workflow studio (`:8188`)
  - `https://grafana.homeserve.lan` — Grafana (`13.2.1`, provisioned dashboards)
  - `https://kuma.homeserve.lan` — Uptime Kuma (`2.5.3`, `:3002`)
  - `https://prom.homeserve.lan` — Prometheus (`v3.14.0`, `:9091`)
  - `https://gateway.homeserve.lan` — Agent Gateway OpenAPI tool server (`:8090`, bearer-key auth)
  - `https://ntfy.homeserve.lan` — Self-hosted ntfy push notification server (`:2586`)
  - `https://auth.homeserve.lan` & `https://lldap.homeserve.lan` — Authelia SSO portal & LLDAP directory
- **Firewall & Isolation:** Container ports bind strictly to `127.0.0.1`, `192.168.0.148`, and `100.65.105.46` (never `0.0.0.0` to the public internet). UFW denies unsolicited inbound traffic by default.

---

## Architecture & Latest Features

### 1. Local RTX 5060 GPU Inference, Embeddings & ComfyUI (`compose/ai-node.yml`)
- **Ollama (`ai-ollama`, `:11434`):** Runs `ollama/ollama:latest` directly on the local NVIDIA RTX 5060 GPU with persistent storage in `/srv/ai-node/data/ollama`. Installed models include:
  - `qwen3:8b` (primary local reasoning & coding model)
  - `moondream:latest` (vision-language model)
  - `hf.co/AtomicChat/LFM3-1.7B-Uncensored-GGUF:Q6_K` (fast lightweight model)
  - `all-minilm:latest` (384-dimensional embedding model)
- **OpenAI-Compatible Embeddings (`ai-embeddings`, `:8081`):** FastAPI service (`services/embedding/app.py`) exposing `/v1/embeddings`, `/v1/models`, and `/health`, backed by Ollama `all-minilm` (384-dimensional vectors).
- **ComfyUI (`ai-comfyui`, `:8188`):** Runs `yanwk/comfyui-boot:cu130-slim-v2` on the local RTX 5060 (`mem_limit: 6g`) with persistent directories under `/srv/ai-node/data/comfyui/{models,custom_nodes,input,output,user,cache}` and Prometheus metrics exported at `/api/sites/metrics`.
- **Cooperative GPU Lease Scheduler (`ai-gpu-scheduler`, `127.0.0.1:8077`):** Arbitrates exclusive GPU leases (`/acquire`, `/release`, `/state`) so heavy ComfyUI renders and LLM jobs do not collide on the 8 GiB VRAM budget.

### 2. Three-Tier Agent Gateway & Open WebUI Coding Agent (`services/agent-gateway/`)
- **`ai-agent-gateway` (`:8090`, `services/agent-gateway/app.py`):** Bearer-key authenticated OpenAPI tool server providing:
  - Symlink-safe (`O_NOFOLLOW`) & dirfd-pinned workspace file tools (`fs_list`, `fs_read`, `fs_write`, `fs_mkdir`, `fs_delete`, `fs_hash`)
  - Sandboxed workspace shell execution (`shell_exec` -> `ai-agent-shell:8091`, up to 4-hour `14400s` timeout)
  - Approved host-level execution (`host_exec` -> `ai-agent-host:8092`, SHA-256 audited)
  - Network & TLS diagnostic tools (`http_security_check`, `tcp_probe`, `dns_lookup`, `tls_certificate`)
  - Append-only JSONL audit trail at `/srv/ai-node/agent-platform/artifacts/agent-audit.jsonl`
- **`ai-agent-shell` (`:8091` internal, `Dockerfile.shell` & `shell-worker.py`):** Non-root (`10001:1000`), `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`, `pids_limit: 256` container on the isolated `ai-node-agent-exec` bridge network with Git, Node 22, Corepack/pnpm, and Python 3.
- **`ai-agent-host` (`:8092` internal, `Dockerfile.host` & `host-worker.py`):** Host namespace executor (`nsenter -t 1 -m -u -i -n -p`) on the internal `ai-node-agent-host` network, gated by Open WebUI tool approval (`"tool_approval_mode":"ask"`).

### 3. Autonomous 9-Agent Fleet Supervisor (`services/agent-fleet/`)
Managed 24/7 by user systemd unit `homeserv-agent-fleet.service` (`fleet_supervisor.py`):
- **3 Marketing Agents (`marketing_agents.py` & `master_taxonomies.py`):** Procedural content & visual synthesis across 105+ curated topics with anti-repetition tracking (`/srv/ai-node/data/agent_fleet/used_topics.json`) and Schema.org FAQ generation aligned to `printdeck.net`, `horizonsvc.com`, and `gighound.net`.
- **3 Maintenance Agents (`maintenance_agents.py`):** Automated content publishing, hourly local + public synthetic health probes, and RFC1918/Tailscale-guarded public IndexNow pings.
- **3 Cleanup & Governance Agents (`cleanup_agents.py` & `gpu_queue.py`):** Single-flight RTX 5060 GPU queue serialization, post-render VRAM cache defragmentation (`/free`), 4-hour rolling `site_fleet` backups, and proactive disk threshold (`85%`) ntfy alerts.

### 4. Automated Backups, Restore Verification & Weekly Cleanup (`scripts/`)
- **Nightly Local Backup (`scripts/backup.sh` via `ai-node-backup.timer`):** Pauses stateful containers, creates a `zstd`-compressed archive of `/srv/ai-node` and `/srv/repos` in `/srv/backups/local` (excluding downloadable model weights/caches), verifies the SHA-256 checksum, retains 7 days (minimum 3 newest archives), and writes Prometheus metrics.
- **Encrypted Offsite Backup (`scripts/backup-offsite.sh` via `ai-node-offsite-backup.timer`):** Restic backup with `--keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune`.
- **Disk-Backed Restore Test (`scripts/restore-test.sh` via `ai-node-restore-test.timer`):** Extracts and verifies the latest backup archive in disk-backed `/var/tmp` (avoiding exhaustion of the 7.1 GiB RAM `tmpfs` on `/tmp`).
- **Weekly Filesystem Cleanup (`scripts/weekly-cleanup.sh`):** Prunes unused Docker containers/images/build cache (`>168h`), rotates expired local and `site_fleet` backups, clears temporary caches, and publishes `ai_node_weekly_cleanup_last_success_unixtime_seconds` to Prometheus.

---

## Common Commands

```bash
# 1. Host, container, GPU, and disk status
/srv/ai-node/scripts/status.sh
/srv/ai-node/scripts/health-check.sh
/srv/ai-node/scripts/gpu-status.sh
/srv/ai-node/scripts/disk-status.sh

# 2. Manage the Docker Compose stack
cd /srv/ai-node
docker compose --env-file .env -f compose/ai-node.yml ps
docker compose --env-file .env -f compose/ai-node.yml up -d
docker compose --env-file .env -f compose/ai-node.yml logs --tail=100 ai-agent-gateway

# 3. Run unit tests for Agent Gateway & Embeddings
docker exec ai-agent-gateway python3 -m unittest test_app.py
docker exec ai-embeddings python3 -m unittest test_app.py

# 4. Check user-level autonomous fleet services
systemctl --user status homeserv-agent-fleet.service para-enterprise.service answered.service gighound-growth.service

# 5. Run verified backup, restore test, or weekly cleanup
sudo /srv/ai-node/scripts/backup.sh
sudo /srv/ai-node/scripts/restore-test.sh
sudo /srv/ai-node/scripts/weekly-cleanup.sh
```

For complete step-by-step instructions, see **[docs/HOWTO.md](docs/HOWTO.md)**.
