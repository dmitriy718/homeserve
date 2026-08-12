# homeserv AI node

`homeserv` is an Ubuntu 26.04 headless laptop server providing GPU inference, development workers, monitoring, and persistent application storage. Application workloads are managed by Docker Compose; host changes and all non-secret stack configuration are recorded in this repository.

## Access and network boundary

- LAN: `192.168.1.68` on Wi-Fi; SSH with `ssh dima@homeserv` or `ssh dima@192.168.1.68`.
- Tailscale: `100.65.105.46`; SSH with `ssh dima@100.65.105.46`.
- Application URLs and ports are listed in [SERVICE_MAP.md](SERVICE_MAP.md).
- Container ports bind only to the LAN and Tailscale addresses. UFW denies unsolicited inbound traffic by default and permits the application ports only from `192.168.1.0/24` or `tailscale0`.
- Open WebUI and Grafana anonymous viewing are intentionally usable only inside those trusted networks. Do not forward these ports at the router.

## Architecture and storage

- `/srv/ai-node`: this repository, Compose definition, scripts, monitoring configuration, and persistent application state.
- `/srv/models/ollama`: Ollama model store. The verified model is `qwen3:4b`.
- `/srv/models/embeddings`: cached `sentence-transformers/all-MiniLM-L6-v2` files.
- `/srv/models/comfyui`: ComfyUI checkpoints, VAEs, LoRAs, and related model directories.
- `/srv/repos`: long-lived repositories; `/srv/repos/agents` is reserved for agent work.
- `/srv/builds`: retained build workspaces, logs, and artifacts.
- `/srv/backups/local`: local configuration/state archives. This is the same SSD and is not disaster recovery.
- `/srv/ai-node/secrets`: local environment files, mode `0700`/`0600`, ignored by Git.

Persistent application data is under `/srv/ai-node/data` and is ignored by Git. Containers use `unless-stopped` restart policies. At boot, `ai-node-stack.service` waits for both the LAN and Tailscale addresses before reconciling Compose, preventing bound-port startup races. JSON container logs rotate at 10 MiB with three files. Prometheus retains at most 30 days or 5 GB. Speedtest Tracker runs daily at 06:00 and retains 365 days.

## Routine operation

Run a concise host and service overview:

```bash
/srv/ai-node/scripts/status.sh
/srv/ai-node/scripts/health-check.sh
/srv/ai-node/scripts/gpu-status.sh
/srv/ai-node/scripts/disk-status.sh
```

Start, stop, or inspect the stack:

```bash
cd /srv/ai-node
docker compose --env-file .env -f compose/ai-node.yml up -d
docker compose --env-file .env -f compose/ai-node.yml stop
docker compose --env-file .env -f compose/ai-node.yml ps
docker compose --env-file .env -f compose/ai-node.yml logs --tail=100 SERVICE
```

Use `sudo systemctl poweroff` for a planned host shutdown. Containers receive Docker's normal graceful stop before system power-off.

The stack boot unit can be inspected or reconciled with `systemctl status ai-node-stack` and `sudo systemctl reload ai-node-stack`.

Update pinned images and locally built services with `/srv/ai-node/scripts/update-stack.sh`. It validates Compose, pulls, rebuilds, restarts, and runs the health check. It deliberately does not delete old images or build cache; review space with `docker system df`, and prune only after confirming rollback images are no longer needed.

Validate repository and deployment configuration without changing the running stack:

```bash
/srv/ai-node/scripts/validate-config.sh --strict
```

The August 2026 hardening and usefulness pass is recorded as [exactly 25 scoped improvements](docs/IMPROVEMENTS_2026-08-10.md).

## AI operation

Ollama's API is `http://192.168.1.68:11434` (or the Tailscale address). List models with `docker exec ai-ollama ollama list`; add one deliberately with `docker exec ai-ollama ollama pull MODEL`. Check free SSD space first and avoid loading multiple large models on this 16 GB system.

Open WebUI connects to Ollama on the private Docker network. It runs with WebUI authentication disabled because the host firewall and address bindings define the trust boundary.

The embedding API is OpenAI-compatible:

```bash
curl http://192.168.1.68:8081/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"input":"text to embed"}'
```

It uses `sentence-transformers/all-MiniLM-L6-v2` on CPU and returns 384-dimensional normalized vectors.

ComfyUI has persistent `models`, `custom_nodes`, `input`, `output`, and `user` directories. No generative checkpoint is downloaded automatically. Place a compatible checkpoint under `/srv/models/comfyui/checkpoints`, then select it in a workflow. The installation itself was verified with CUDA and a model-free image workflow. Install custom nodes only after review.

## Development workers

The reproducible Playwright smoke test is:

```bash
cd /srv/ai-node
docker compose --env-file .env -f compose/ai-node.yml --profile dev run --rm playwright
```

`scripts/run-agent-job.sh HTTPS_REPOSITORY JOB_ID 'COMMAND'` clones into a new retained job directory and runs the command in a disposable, network-disabled container. See [docs/AGENT_ISOLATION.md](docs/AGENT_ISOLATION.md). Agent containers receive no Docker socket, host root, SSH keys, credential stores, or unrelated data.

The GitHub Actions foundation is documented in [config/github-runner/README.md](config/github-runner/README.md). Registration is intentionally pending a repository/organization URL and short-lived token. The dedicated `github-runner` user has neither sudo nor Docker access.

## Monitoring

Prometheus scrapes host, GPU, and internal service metrics plus blackbox probes for the gateway, Internet ICMP, DNS, and HTTP endpoints. It evaluates local alerts for unavailable targets and probes, disk and memory pressure, high GPU temperature, failed GPU telemetry, and stale or missing verified backups; inspect them at `http://192.168.1.68:9091/alerts`. Grafana provisions the Prometheus datasource and `AI Node Overview` dashboard from files, including verified-backup age and firing-alert counts. Speedtest Tracker records a daily test. Uptime Kuma uses SQLite and has an initialized admin account; Prometheus blackbox monitoring is active independently of user-defined Kuma monitors.

Generated Grafana, Speedtest Tracker, and Uptime Kuma credentials are stored only in `/srv/ai-node/secrets/*.env` and the corresponding service databases. Retrieve them locally with `sudo`, do not copy them into this repository, and rotate them from the applications after first login if desired.

## Backup and restore

Run `sudo /srv/ai-node/scripts/backup.sh`. It briefly pauses stateful web containers, archives configuration, secrets, databases, workflows, and `/srv/repos`, excludes Prometheus history and downloadable caches/models, read-tests the archive, verifies a SHA-256 sidecar, publishes status and Prometheus freshness records, and keeps 14 days of local archives. After installing and enabling `ai-node-backup.timer`, the same verified backup runs nightly around 03:30 America/New_York with a randomized delay.

For real disaster recovery, attach and mount an external disk or NAS, then run:

```bash
sudo BACKUP_DEST=/mnt/verified-backup-target /srv/ai-node/scripts/backup.sh
```

Verify the target is truly a separate mounted filesystem. To restore, stop the stack, verify the archive with `sha256sum -c ARCHIVE.sha256`, inspect it with `tar --zstd -tf ARCHIVE`, and extract from `/` with `sudo tar --zstd --acls --xattrs -xpf ARCHIVE -C /`. Restore secrets with mode `0600`, confirm service-data ownership, then start the stack and run `health-check.sh`. Model weights must be downloaded again.

## Troubleshooting and security

- GPU: `nvidia-smi`, then `/srv/ai-node/scripts/gpu-status.sh` for the host and container test.
- Docker: `systemctl status docker`, `docker info`, and Compose logs.
- Failed host units: `systemctl --failed`; network and DNS: `ip route`, `resolvectl status`, `tailscale status`.
- Metrics target failures: `http://192.168.1.68:9091/targets`.
- Disk pressure: `disk-status.sh`; models are the first large, replaceable data to review.
- RAM pressure: `free -h` and `docker stats --no-stream`. Avoid simultaneous Ollama, ComfyUI generation, and large builds.
- Never commit `.env`, `secrets`, databases, logs, backups, model weights, or generated output. Docker-group membership is root-equivalent. Do not mount `/var/run/docker.sock` into untrusted workloads.
