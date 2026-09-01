#!/usr/bin/env bash
set -euo pipefail
[[ -d /srv/ai-node ]] || echo "warning: not the ai-node host; showing THIS machine's status" >&2
df -hT
echo
sudo lvs -o lv_name,vg_name,lv_size,data_percent 2>/dev/null || true
echo
docker system df
echo
du -xhd1 /srv 2>/dev/null | sort -h
echo
sudo nvme smart-log /dev/nvme0 2>/dev/null || sudo smartctl -a /dev/nvme0 2>/dev/null || true

