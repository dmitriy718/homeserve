#!/usr/bin/env bash
set -euo pipefail

# Environment:
#   JOB_TIMEOUT   Wall-clock limit for the job container in seconds (default 1800).
#                 On expiry the container is stopped and the script fails.
# Flags:
#   --cleanup     Delete /srv/builds/agents/* job directories older than 14 days and exit.

if [[ ${1:-} == --cleanup ]]; then
  find /srv/builds/agents -mindepth 1 -maxdepth 1 -type d -mtime +14 -print -exec rm -rf -- {} +
  exit 0
fi

if (($# < 2)); then
  echo "Usage: $0 HTTPS_REPOSITORY JOB_ID [COMMAND] | $0 --cleanup" >&2
  exit 2
fi

job_timeout=${JOB_TIMEOUT:-1800}
[[ $job_timeout =~ ^[0-9]+$ ]] || { echo "JOB_TIMEOUT must be a positive integer (seconds)" >&2; exit 2; }

repo=$1
job_id=$2
shift 2
command=${*:-'npm test'}

[[ $repo =~ ^https://[^[:space:]]+$ ]] || { echo "Only HTTPS repository URLs are accepted" >&2; exit 2; }
[[ $job_id =~ ^[a-zA-Z0-9._-]+$ ]] || { echo "Unsafe job ID" >&2; exit 2; }

job_root="/srv/builds/agents/$job_id"
workspace="$job_root/workspace"
artifacts="$job_root/artifacts"
logs="$job_root/logs"
[[ ! -e $job_root ]] || { echo "Job already exists: $job_root" >&2; exit 2; }
mkdir -p "$workspace" "$artifacts" "$logs"

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 256 \
  --memory 1g \
  --cpus 2 \
  -v "$workspace:/workspace" \
  alpine/git:2.49.1 clone --depth 1 "$repo" /workspace

timeout --kill-after=30s "${job_timeout}s" \
  docker run --rm \
  --user "1000:1000" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 512 \
  --memory 4g \
  --cpus 4 \
  --network none \
  --stop-timeout 15 \
  --tmpfs /tmp:rw,noexec,nosuid,size=512m \
  -e HOME=/tmp/home \
  -v "$workspace:/workspace:rw" \
  -v "$artifacts:/artifacts:rw" \
  -w /workspace \
  node:24-bookworm \
  bash -lc "git switch -c agent/$job_id >/dev/null 2>&1 || true; $command" \
  2>&1 | tee "$logs/job.log"

echo "Workspace preserved: $workspace"
echo "Artifacts: $artifacts"
echo "Log: $logs/job.log"

