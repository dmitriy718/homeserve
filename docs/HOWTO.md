# Homeserv (`ai-node`) — Complete How-To & Operator Guide

This guide covers day-to-day administration, LLM & GPU management, the 3-tier Coding Agent Gateway, the 9-Agent Autonomous Fleet Supervisor, monitoring/alerts, and backup/restore operations on `homeserv`.

---

## Table of Contents
1. [SSH, Tailscale & Local HTTPS Setup](#1-ssh-tailscale--local-https-setup)
2. [Day-to-Day Stack Operations & Health Checks](#2-day-to-day-stack-operations--health-checks)
3. [Managing Ollama Models, Embeddings & RTX 5060 VRAM](#3-managing-ollama-models-embeddings--rtx-5060-vram)
4. [Using Open WebUI & the 3-Tier Coding Agent Gateway](#4-using-open-webui--the-3-tier-coding-agent-gateway)
5. [Operating the 9-Agent Autonomous Fleet (`services/agent-fleet/`)](#5-operating-the-9-agent-autonomous-fleet-servicesagent-fleet)
6. [Monitoring, Prometheus Metrics & `ntfy` Push Alerts](#6-monitoring-prometheus-metrics--ntfy-push-alerts)
7. [Backups, Offsite Sync, Restore Testing & Weekly Cleanup](#7-backups-offsite-sync-restore-testing--weekly-cleanup)
8. [Troubleshooting & Emergency Runbooks](#8-troubleshooting--emergency-runbooks)

---

## 1. SSH, Tailscale & Local HTTPS Setup

### Connecting via SSH
`homeserv` is reachable over both the local LAN (`192.168.0.148`) and Tailscale (`100.65.105.46`) using standard OpenSSH Ed25519 keys:

```bash
# Via SSH config alias or Tailscale IP
ssh homeserv
ssh dima@100.65.105.46

# Direct via local LAN IP
ssh dima@192.168.0.148
```

### Keeping Tailscale SSH Interception Disabled (Unattended Watchdog Access)
To ensure `sshd` (port `22`) handles key-based SSH directly on `100.65.105.46` without triggering Tailscale's interactive 12-hour browser re-authentication prompt:

```bash
sudo tailscale set --ssh=false --operator=dima
tailscale debug prefs | grep -E "RunSSH|OperatorUser"
# Expected:
#   "RunSSH": false,
#   "OperatorUser": "dima",
```

### Recommended Client `~/.ssh/config` Entry
```ssh-config
Host homeserv 100.65.105.46 192.168.0.148
    HostName 100.65.105.46
    User dima
    StrictHostKeyChecking accept-new
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

### Setting Up `*.homeserve.lan` & Trusting the Caddy Root CA
1. Add the following entry to `/etc/hosts` on your workstation (or configure a wildcard in your router/Pi-hole):
   ```text
   100.65.105.46 homeserve.lan webui.homeserve.lan comfy.homeserve.lan grafana.homeserve.lan kuma.homeserve.lan prom.homeserve.lan gateway.homeserve.lan ntfy.homeserve.lan auth.homeserve.lan lldap.homeserve.lan
   ```
2. Export and trust Caddy's internal root CA:
   ```bash
   ssh homeserv "docker cp edge-caddy:/data/caddy/pki/authorities/local/root.crt -" > homeserv-caddy-root.crt
   # macOS:
   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain homeserv-caddy-root.crt
   ```

---

## 2. Day-to-Day Stack Operations & Health Checks

### Run the Built-In Diagnostic Scripts
```bash
/srv/ai-node/scripts/status.sh        # Container states, ports, and resource summary
/srv/ai-node/scripts/health-check.sh  # End-to-end probe of all Compose services and endpoints
/srv/ai-node/scripts/gpu-status.sh    # Host nvidia-smi + container GPU access check
/srv/ai-node/scripts/disk-status.sh   # Filesystem usage & largest directories under /srv
```

### Start, Stop, Restart, or Inspect Services
```bash
cd /srv/ai-node

# Check running containers
docker compose --env-file .env -f compose/ai-node.yml ps

# Reconcile / start any stopped services
docker compose --env-file .env -f compose/ai-node.yml up -d

# Restart a single service (e.g., open-webui or agent-gateway)
docker compose --env-file .env -f compose/ai-node.yml restart open-webui

# Tail logs for a service
docker compose --env-file .env -f compose/ai-node.yml logs -f --tail=100 agent-gateway
```

### Safe Stack Deployment & Image Updates
```bash
# Preview changes without modifying running containers
sudo /srv/ai-node/scripts/deploy.sh --dry-run

# Pull latest git changes, rebuild local images, recreate changed containers, and verify health
sudo /srv/ai-node/scripts/deploy.sh

# Rebuild/pull images without git fast-forward
sudo /srv/ai-node/scripts/update-stack.sh
```

---

## 3. Managing Ollama Models, Embeddings & RTX 5060 VRAM

`homeserv` has an **8 GiB NVIDIA GeForce RTX 5060 Laptop GPU** shared between `ai-ollama` and `ai-comfyui`.

### List, Pull, or Remove Ollama Models
```bash
# List installed models
docker exec ai-ollama ollama list

# Check currently loaded models in VRAM
docker exec ai-ollama ollama ps

# Pull a new model
docker exec ai-ollama ollama pull qwen3:8b

# Remove an unused model
docker exec ai-ollama ollama rm <model_name>
```

### Query Ollama & the OpenAI-Compatible Embedding Service (`:8081`)
```bash
# Test chat generation on Ollama (:11434)
curl -sS http://127.0.0.1:11434/api/generate \
  -d '{"model":"qwen3:8b","prompt":"Summarize single-host Docker hardening in 2 sentences.","stream":false}' | jq -r .response

# Generate 384-dimensional normalized embeddings via ai-embeddings (:8081)
curl -sS http://127.0.0.1:8081/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"all-minilm","input":["first document","second document"]}' | jq '.data | length, .[0].embedding | length'
```

### Cooperative GPU Lease Scheduler (`127.0.0.1:8077`) & Freeing ComfyUI VRAM
```bash
# Inspect current GPU lease state
curl -sS http://127.0.0.1:8077/state | jq .

# Acquire a 10-minute GPU lease for a batch job
curl -sS -X POST http://127.0.0.1:8077/acquire \
  -H "Content-Type: application/json" \
  -d '{"holder":"manual-batch","ttl_seconds":600}'

# Release the GPU lease
curl -sS -X POST http://127.0.0.1:8077/release \
  -H "Content-Type: application/json" \
  -d '{"holder":"manual-batch"}'

# Force ComfyUI to unload models and free PyTorch CUDA cache
curl -sS -X POST http://127.0.0.1:8188/free \
  -H "Content-Type: application/json" \
  -d '{"unload_models":true,"free_memory":true}'
```

---

## 4. Using Open WebUI & the 3-Tier Coding Agent Gateway

### Architecture Overview
The Agent Gateway (`services/agent-gateway/`) separates tool routing from command execution across three containers:
1. **`ai-agent-gateway` (`:8090`):** Authenticates requests via `X-Agent-Key` / `Authorization: Bearer`, enforces workspace path sandboxing (`/srv/ai-node/agent-platform/workspaces`), logs every call to `/srv/ai-node/agent-platform/artifacts/agent-audit.jsonl`, and dispatches shell calls.
2. **`ai-agent-shell` (`:8091` internal):** Runs workspace commands as unprivileged UID `10001:1000` with `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`, `pids_limit: 256`, and up to a 4-hour (`14400s`) timeout.
3. **`ai-agent-host` (`:8092` internal):** Executes approved host-level commands via `nsenter` into PID 1 namespaces (`host_exec`).

### Calling the Agent Gateway Directly via CLI
```bash
AGENT_KEY=$(sudo cat /srv/ai-node/secrets/agent-gateway.key)

# 1. List available tools
curl -sS http://127.0.0.1:8090/tools \
  -H "X-Agent-Key: $AGENT_KEY" | jq .

# 2. Run an isolated command inside a project workspace (ai-agent-shell)
curl -sS -X POST http://127.0.0.1:8090/shell/exec \
  -H "X-Agent-Key: $AGENT_KEY" \
  -H "Content-Type: application/json" \
  -d '{"project":"test","command":"git status && node -v && pnpm -v","timeout_seconds":60}' | jq .

# 3. Inspect the recent Agent Gateway audit log
tail -n 20 /srv/ai-node/agent-platform/artifacts/agent-audit.jsonl | jq .
```

### Running the Agent Gateway & Embedding Unit Tests
```bash
docker exec ai-agent-gateway python3 -m unittest test_app.py
docker exec ai-embeddings python3 -m unittest test_app.py
```

---

## 5. Operating the 9-Agent Autonomous Fleet (`services/agent-fleet/`)

`homeserv-agent-fleet.service` runs `/srv/ai-node/services/agent-fleet/fleet_supervisor.py` continuously as a user-level systemd service under `dima`.

### Check Status & Live Logs
```bash
systemctl --user status homeserv-agent-fleet.service
journalctl --user -u homeserv-agent-fleet.service -f -n 100
```

### Trigger an On-Demand Content & ComfyUI Render Cycle
Write a JSON trigger file to `/srv/ai-node/data/comfyui/custom_nodes/site_host_hub/data/trigger.json` (`site_id` can be `pulsegrid` for PrintDeck, `autonomouse` for HorizonSVC, or `tradeloom` for GigHound; `cadence` can be `hero` or `masterpiece`):

```bash
printf '{"site_id": "pulsegrid", "cadence": "hero"}\n' > /srv/ai-node/data/comfyui/custom_nodes/site_host_hub/data/trigger.json
```

The Fleet Supervisor polls for `trigger.json` every 5 seconds, runs the Marketing -> ComfyUI -> Maintenance pipeline, verifies site health, and removes the trigger file.

### Manage All User-Level Autonomous Services on `homeserv`
```bash
# Check all active user services and timers
systemctl --user list-units "homeserv-*" "para-*" "answered*" "gighound-*"

# Restart a specific daemon
systemctl --user restart homeserv-agent-fleet.service
systemctl --user restart para-enterprise.service
```

---

## 6. Monitoring, Prometheus Metrics & `ntfy` Push Alerts

- **Prometheus UI & Alerts:** `http://192.168.0.148:9091/alerts` (or `https://prom.homeserve.lan/alerts`)
- **Grafana UI:** `https://grafana.homeserve.lan` (provisioned `AI Node Overview` dashboard)
- **Uptime Kuma UI:** `http://192.168.0.148:3002` (or `https://kuma.homeserve.lan`)

### Subscribe to Self-Hosted `ntfy` Push Alerts
```bash
# Stream alerts in terminal
curl -N http://192.168.0.148:2586/homeserve-alerts/json
curl -N http://192.168.0.148:2586/homeserve-alerts-critical/json

# Send a test notification
curl -H "Title: Homeserv Test" -H "Priority: default" \
  -d "Test notification from homeserv CLI" \
  http://127.0.0.1:2586/homeserve-alerts
```

---

## 7. Backups, Offsite Sync, Restore Testing & Weekly Cleanup

### Run a Verified Local Backup (`scripts/backup.sh`)
Creates a `zstd`-compressed archive in `/srv/backups/local/ai-node-YYYYMMDD-HHMMSS.tar.zst` (plus `.sha256`), pausing stateful containers briefly and retaining 7 days of archives (minimum 3 newest):

```bash
sudo /srv/ai-node/scripts/backup.sh
ls -lh /srv/backups/local/
```

### Run an Encrypted Offsite Restic Backup (`scripts/backup-offsite.sh`)
Requires `/srv/ai-node/secrets/restic.env` (copied from `secrets/restic.env.example` with `RESTIC_REPOSITORY` configured):

```bash
sudo /srv/ai-node/scripts/backup-offsite.sh
```

### Run a Non-Destructive Restore Verification (`scripts/restore-test.sh`)
Extracts the newest `.tar.zst` archive into disk-backed `/var/tmp` (preventing RAM `tmpfs` exhaustion on `/tmp`), verifies SHA-256 integrity and key files, and cleans up the scratch directory:

```bash
sudo /srv/ai-node/scripts/restore-test.sh
```

### Run the Weekly Filesystem & Docker Cleanup (`scripts/weekly-cleanup.sh`)
Prunes unused Docker containers/images/builders older than 7 days (`168h`), rotates expired local and `site_fleet` backups, clears pip/npm/ComfyUI temporary caches, and updates Prometheus textfile metrics:

```bash
sudo /srv/ai-node/scripts/weekly-cleanup.sh
```

---

## 8. Troubleshooting & Emergency Runbooks

1. **ComfyUI or Ollama CUDA Out-of-Memory (OOM):**
   - Free ComfyUI VRAM first: `curl -X POST http://127.0.0.1:8188/free -H "Content-Type: application/json" -d '{"unload_models":true,"free_memory":true}'`
   - Or unload idle Ollama models: `docker restart ai-ollama`
2. **Container Unhealthy After Reboot or IP Change:**
   - Verify `LAN_IP` and `TAILSCALE_IP` in `/srv/ai-node/.env` match `ip -4 addr` and `tailscale ip -4`.
   - Reconcile stack: `sudo systemctl reload ai-node-stack` or `cd /srv/ai-node && docker compose --env-file .env -f compose/ai-node.yml up -d`.
3. **Resetting Open WebUI / Authelia SSO Access:**
   - LLDAP admin credentials are stored in `/srv/ai-node/secrets/lldap.env` (`LLDAP_LDAP_USER_PASS`).
   - Open `https://lldap.homeserve.lan` on the LAN/Tailscale network to manage users or reset passwords.
4. **Full Disaster Recovery:**
   - Follow [docs/DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) for bare-metal restoration from `/srv/backups/local` or Restic offsite snapshots.
