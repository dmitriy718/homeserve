# Initial system baseline

Recorded before provisioning on 2026-08-08.

- OS: Ubuntu Server 26.04 LTS, kernel `7.0.0-29-generic`, x86-64, hostname `homeserv`.
- Platform: HP OMEN 16-ap0xxx; AMD Ryzen AI 7 350 with Radeon 860M, 8 cores/16 threads; approximately 16 GB installed RAM (14 GiB usable); 4 GiB swap.
- Storage: Samsung PM9C1a approximately 1 TB NVMe. The existing LVM root filesystem was only 100 GB although the volume group had about 850.8 GB unallocated.
- NVIDIA: GeForce RTX 5060 Laptop GPU (`10de:2d19`) present on PCIe. Nouveau was loaded; no NVIDIA proprietary/open driver or working `nvidia-smi` was present. Secure Boot was disabled.
- AMD graphics: integrated Radeon 840M/860M using `amdgpu`.
- Network: MediaTek MT7922 Wi-Fi active at `192.168.1.68/24`, gateway/DNS `192.168.1.1`; Realtek RTL8111/8168 Ethernet disconnected. Tailscale and UFW were not configured.
- Services: SSH active. Docker was not installed. Existing Snap-managed Nextcloud, Wekan, Prometheus, LXD, etcd, and keepalived workloads were discovered and preserved.
- Faults: `systemd-networkd-wait-online.service` failed because the disconnected Ethernet interface was mandatory. Internet access was intermittently unavailable during the first provisioning attempt.
- Laptop behavior: default lid/power behavior was unsuitable for a closed-lid always-on server.

The existing partition table was not changed. The existing root logical volume and filesystem were extended online to use 850 GB of the already-free LVM space.

