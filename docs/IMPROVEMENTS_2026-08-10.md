# Home server improvement set — 2026-08-10

This change set contains exactly 25 scoped improvements. It is designed for the existing 16 GB GPU laptop host and does not add another always-running application or expose another port.

1. Enable a tiny init process in compatible long-running Compose services so orphaned child processes are reaped; retain PID 1 for LinuxServer's s6-overlay.
2. Cap each long-running service at 1,024 processes to limit fork bombs and runaway workers.
3. Give services and the systemd stop path a 45-second graceful shutdown window for safer database and application stops.
4. Sandbox the agent gateway with a read-only root filesystem, no Linux capabilities, a constrained temporary filesystem, a two-CPU ceiling, and explicit readable application-file modes for unprivileged custom images.
5. Refuse to start the agent gateway unless its API key is at least 32 characters.
6. Compare gateway credentials with a constant-time comparison.
7. Bound gateway write bodies and shell-command lengths to prevent oversized requests from exhausting memory or storage.
8. Rotate the gateway audit log at 10 MiB so it cannot grow forever.
9. Limit embedding requests to 64 inputs and 50,000 total characters.
10. Make NVIDIA exporter health accurately fail when `nvidia-smi` returns no usable GPU rows.
11. Add a native Docker health check for Grafana.
12. Add a native Docker health check and container hardening for the NVIDIA exporter.
13. Add the agent gateway to Prometheus blackbox HTTP monitoring.
14. Add Prometheus alerts for scrape/probe failures, root-disk pressure, memory pressure, GPU heat, missing GPU telemetry, and stale or missing verified backups.
15. Refuse an external-backup path under `/mnt` or `/media` when it is still on the root filesystem.
16. Write backups to a partial name, read-test the archive, and verify its SHA-256 sidecar before declaring success.
17. Expire old backup archives, checksum sidecars, and abandoned partial archives together.
18. Add a persistent, randomized nightly systemd backup timer with low I/O priority.
19. Lock stack updates so two update jobs cannot overlap, and wait for the whole stack to become healthy after an update.
20. Add a preflight validator covering shell syntax/static analysis, Python, Grafana JSON, Compose, required secrets, and Prometheus rules when its image is available.
21. Add a validation-only Compose override so repository checks work without copying real secrets into a development checkout.
22. Extend the health check with root filesystem and inode usage thresholds.
23. Extend the health check with the agent gateway and unhealthy Compose-container detection.
24. Extend the status report with unhealthy containers, backup age, and pending-reboot state.
25. Harden host access and recovery: require SSH public keys, disable agent forwarding/tunnels/gateway ports, tighten session limits and logging, and retry failed stack starts with a restrictive umask.

## Activation checklist

Review the diff before copying it to `/srv/ai-node`. The gateway key must contain at least 32 characters before rebuilding. On the server, run:

```bash
cd /srv/ai-node
./scripts/validate-config.sh --strict
sudo install -m 0644 host/etc/systemd/system/ai-node-stack.service /etc/systemd/system/ai-node-stack.service
sudo install -m 0644 host/etc/systemd/system/ai-node-backup.service /etc/systemd/system/ai-node-backup.service
sudo install -m 0644 host/etc/systemd/system/ai-node-backup.timer /etc/systemd/system/ai-node-backup.timer
sudo install -m 0644 host/etc/ssh/sshd_config.d/10-ai-node-hardening.conf /etc/ssh/sshd_config.d/10-ai-node-hardening.conf
sudo sshd -t -f /etc/ssh/sshd_config
sudo systemctl daemon-reload
sudo systemctl enable --now ai-node-backup.timer
sudo systemctl reload ssh
./scripts/update-stack.sh
```

Keep the current SSH session open while testing a second public-key login after reloading SSH. The timer writes to the existing local backup destination; a separate mounted `BACKUP_DEST` is still required for disaster recovery.

Prometheus evaluates and displays the new alerts at `/alerts`. No external notifications are sent because Alertmanager contact details are intentionally not guessed.

> **Addendum (2026-09-01):** the last sentence is superseded — Alertmanager now posts alerts to the self-hosted ntfy service (topics `homeserve-alerts` and `homeserve-alerts-critical`); see `monitoring/alertmanager.yml` and the README.
