# Disaster recovery runbook

Full rebuild of the AI node from bare metal. Assumes the hardware is
replacement or wiped, and that at least one of these exists:

- a local archive in `/srv/backups/local` (or an external `BACKUP_DEST`
  copy) with its `.sha256` sidecar, or
- a restic offsite repository plus its password file
  (`/srv/ai-node/secrets/restic-password` — keep a copy off the host).

Estimated time: 1–2 hours plus model re-downloads.

## 1. Base operating system

1. Install Ubuntu 24.04 LTS with a minimal profile. Create the primary user,
   enable OpenSSH server during install.
2. Apply updates and reboot:
   `sudo apt-get update && sudo apt-get full-upgrade -y && sudo reboot`.

## 2. Docker

1. Install Docker and the Compose plugin:
   `sudo apt-get install -y docker.io docker-compose-v2` and
   `sudo systemctl enable --now docker` (the installer also does this; see
   [Docker's official docs](https://docs.docker.com/engine/install/ubuntu/)
   if you prefer the upstream repository).

## 3. NVIDIA driver and container toolkit (GPU hosts only)

1. Install the driver: `sudo ubuntu-drivers install`, then reboot and confirm
   with `nvidia-smi`. See
   [Ubuntu's NVIDIA driver docs](https://ubuntu.com/server/docs/nvidia-drivers-installation).
2. Install the NVIDIA Container Toolkit per the
   [official install guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
   `scripts/install.sh` will also detect the GPU and install/configure
   `nvidia-container-toolkit` if it is missing.

## 4. Tailscale

1. Install per <https://tailscale.com/download/linux> and log in:
   `sudo tailscale up`. Note the address with `tailscale ip -4`; the stack
   binds ports to it and the installer asks for it.

## 5. Repository and stack install

1. `sudo apt-get install -y git`
2. `sudo git clone https://github.com/<org>/homeserve /srv/homeserve` (any
   scratch path; the installer copies it into `/srv/ai-node`).
3. `cd /srv/homeserve && sudo scripts/install.sh`
   This renders `.env`, generates fresh secrets, installs the systemd units
   (including the backup, offsite-backup, restore-test, SMART, and battery
   timers), validates the config, and starts the stack.

## 6. Restore application data

Stop the stack first: `sudo systemctl stop ai-node-stack`.

### Option A — local archive

Follow the restore steps in the README backup section: verify the archive
with `sha256sum -c ARCHIVE.sha256`, inspect it with
`tar --zstd -tf ARCHIVE`, extract from `/` with
`sudo tar --zstd --acls --xattrs -xpf ARCHIVE -C /`, fix secret modes to
`0600`, and confirm service-data ownership.

### Option B — offsite restic repository

1. Install restic: `sudo apt-get install -y restic`.
2. Recreate `/srv/ai-node/secrets/restic.env` from
   `secrets/restic.env.example` and restore the password file to
   `/srv/ai-node/secrets/restic-password` (mode `0600`).
3. `sudo -i`, source the env file, then:
   `restic restore latest --target /srv/ai-node-restore`
4. `sudo rsync -a /srv/ai-node-restore/srv/ai-node/ /srv/ai-node/`
   and remove `/srv/ai-node-restore` when satisfied.

## 7. Secrets: restore vs regenerate

Restored secrets (from either option) preserve Grafana, Speedtest, Uptime
Kuma, and gateway logins. If the secrets directory is lost, the installer
has already generated fresh ones — logins revert to the generated
credentials in `/srv/ai-node/secrets/*.env` and per-application databases
must be recreated. Never mix: an application database restored alongside a
regenerated secret for that application will fail authentication; prefer
restoring the full `secrets/` directory with the data.

## 8. Acceptance checks

1. `sudo /srv/ai-node/scripts/validate-config.sh --strict` — must pass.
2. Start the stack: `sudo systemctl start ai-node-stack`.
3. `/srv/ai-node/scripts/health-check.sh` — all services healthy.
4. Confirm timers: `systemctl list-timers 'ai-node-*'`.
5. Trigger a manual backup to re-establish the freshness metric:
   `sudo /srv/ai-node/scripts/backup.sh`, then check
   `http://<lan-ip>:9091/alerts` clears `BackupStale`.

## 9. Application accounts and models

- Open WebUI: the first registered account becomes admin. Temporarily set
  `ENABLE_SIGNUP: "True"` in `compose/ai-node.yml`, register, then set it
  back to `"False"` and recreate the container (see the README).
- Grafana: admin password is in `/srv/ai-node/secrets/grafana.env`.
- Model weights are excluded from backups by design; re-pull them, e.g.
  `docker exec ai-ollama ollama pull qwen3:4b`, and re-copy ComfyUI
  checkpoints into `/srv/models/comfyui/checkpoints`.
