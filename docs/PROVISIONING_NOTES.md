# Provisioning notes and resolved failures

- Internet and registry requests initially failed. After connectivity returned, gateway, public IP, DNS, Docker registry, Hugging Face, and Tailscale peer reachability were tested before downloads resumed.
- NVIDIA initially used Nouveau. Ubuntu's hardware recommendation selected `nvidia-driver-595-open`; after installation and reboot, host and CUDA-container `nvidia-smi` both detected the RTX 5060.
- `systemd-networkd-wait-online` failed on disconnected Ethernet. Marking that Netplan interface optional removed the boot failure without disabling Ethernet.
- The first custom embedding build selected CUDA-bearing PyTorch packages. The Dockerfile was corrected to install the official CPU-only PyTorch wheel before sentence-transformers, reducing disk and GPU overhead.
- Repository files initially retained restrictive sync modes, preventing non-root container users from reading code and Prometheus configuration. Repository paths were normalized to executable directories/readable files, affected images were rebuilt, and each service was retested.
- Prometheus could not write `queries.active` after its data directory ownership changed. Ownership was restored to its container UID and readiness plus every scrape target were verified.
- ComfyUI's first model-free workflow could not save because its empty output directory had disappeared during a staging synchronization. Persistent directories were recreated, the container restarted, and the workflow then produced `verification_00001_.png` successfully.
- Open WebUI's HTTP health and Ollama proxy initially worked while its background scheduler exposed a partially initialized SQLite schema. With no user chats present, the damaged directory was quarantined, a clean database was migrated, the `chat` table and scheduler were checked, and model discovery plus proxy inference were repeated successfully.
- Speedtest Tracker's SQLite file was missing after the same early synchronization. A dedicated persistent SQLite file was created, migrations initialized it, and a real Ookla test was recorded with status `completed`.
- The first backup attempt ran without enough privilege to read service-owned databases. The script now explicitly elevates, uses a root-owned lock directory, unpauses services via a trap, removes an incomplete archive on failure, and was verified by SHA-256 and archive listing.

Persistent runtime directories are now excluded from configuration synchronization and from Git. Do not deploy this repository with an unqualified `rsync --delete` against `/srv/ai-node`; application data lives below the same tree.
