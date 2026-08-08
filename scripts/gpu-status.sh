#!/usr/bin/env bash
set -euo pipefail
nvidia-smi
echo
echo "GPU processes:"
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv 2>/dev/null || true
echo
echo "GPU from a disposable container:"
docker run --rm --gpus all nvidia/cuda:13.2.0-base-ubuntu24.04 nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

