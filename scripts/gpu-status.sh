#!/usr/bin/env bash
set -euo pipefail

case ${1:-} in
  "") pull=false ;;
  --pull) pull=true ;;
  *) echo "Usage: $0 [--pull]" >&2; exit 2 ;;
esac

nvidia-smi
echo
echo "GPU processes:"
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv 2>/dev/null || true
echo
echo "GPU from a disposable container:"
image=nvidia/cuda:13.2.0-base-ubuntu24.04
if docker image inspect "$image" >/dev/null 2>&1 || $pull; then
  docker run --rm --gpus all "$image" nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
else
  echo "SKIP container GPU check ($image is not present locally; rerun with --pull to fetch it)"
fi

