# GPU scheduling: the cooperative lease arbiter

The ai-node host has a single RTX 5060 Laptop GPU (~8 GB VRAM). Both `ollama`
and `comfyui` get `gpus: all` in `compose/ai-node.yml`, and nothing in Docker
or the NVIDIA container toolkit serializes them: if a ComfyUI workflow starts
while a large model is resident in ollama, one of them hits a silent
`cudaMalloc` failure (OOM at allocation time, mid-request).

`gpu-scheduler` (`services/gpu-scheduler/`) is the answer this repo can
honestly ship today: a **cooperative lease arbiter**. Clients acquire an
exclusive lease before GPU work and release it afterwards. It is not a hard
enforcer — see [Limits](#limits-what-this-is-not).

## API

Base URL: `http://gpu-scheduler:8077` from the `ai`/`scrape` networks, or
`http://127.0.0.1:8077` from the host (published on loopback only — never on
`LAN_IP`/`TAILSCALE_IP`; the LAN has no reason to talk to the arbiter).

| Endpoint | Meaning |
| --- | --- |
| `POST /leases` | Acquire the exclusive lease. Body: `{"holder": "name", "kind": "llm"\|"image"\|"other", "ttl_seconds": 120}`. On conflict: **409** with `queue_position`, unless `?wait=true&wait_timeout=N`, which long-polls until granted (or 409 with `timed_out: true`). Re-acquiring a lease you hold is an idempotent refresh. |
| `DELETE /leases/{holder}` | Release the lease (also drops the holder from the queue). The next queued holder is granted automatically. |
| `POST /leases/{holder}/heartbeat` | Refresh the TTL. Required at least once per `ttl_seconds`. |
| `GET /state` | Current holder (with `expires_in_seconds`), queue with positions, lifetime counters. |
| `GET /metrics` | Prometheus exposition (see below). |

Leases expire `ttl_seconds` after the last heartbeat (default 120 s), so a
crashed client never deadlocks the GPU — the reaper reclaims the lease and
grants it to the next queued holder.

There is no authentication. The container joins only the internal `ai` and
`scrape` networks plus the loopback publish, holds no secrets, and only
coordinates hints; the worst a network-local caller can do is lie about who
holds the lease.

State is **in-memory on purpose**: a scheduler restart wipes leases and queue,
and clients simply re-acquire (TTLs are short, heartbeats cheap). Persisting
leases across a crash would revive stale holders, which is worse.

## Integrating workloads

### Host-side / agent jobs: `scripts/gpu-lock.sh`

On the server (the script lives at `/srv/ai-node/scripts/gpu-lock.sh`):

```bash
/srv/ai-node/scripts/gpu-lock.sh status                          # current holder + queue
/srv/ai-node/scripts/gpu-lock.sh acquire my-job image --wait     # block until granted
/srv/ai-node/scripts/gpu-lock.sh release my-job
/srv/ai-node/scripts/gpu-lock.sh run my-job image -- python train.py   # acquire, heartbeat, run, release
```

`run` is the recommended shape: it acquires (waiting for the lease), sends
heartbeats in the background while the command runs, and releases via an
`EXIT` trap no matter how the command ends.

Agent-gateway `shell_exec` jobs that touch the GPU should be wrapped the same
way — prefix the command with `gpu-lock.sh run <project> other --` (the
gateway container would need the script bind-mounted and `GPU_SCHEDULER_URL`
pointed at `http://gpu-scheduler:8077`; not wired by default).

### ComfyUI

ComfyUI itself cannot be forced through the arbiter. A front-end or workflow
runner can poll `GET /state` and warn (or hold the prompt) when the lease is
held by an `llm` holder — the honest UX improvement without patching ComfyUI.

### Open WebUI / ollama

Same story: Open WebUI talks straight to ollama. A small proxy or a custom
Open WebUI function could call `/state` before sending a chat request and
surface "GPU busy with image generation" instead of an opaque failure.

## Metrics and alerts

Scraped by the `gpu-scheduler` Prometheus job (`gpu-scheduler:8077/metrics`):

- `gpu_lease_active{holder,kind}` — 1 for the current holder
- `gpu_lease_started_unixtime{holder,kind}` — grant timestamp (drives `GpuLeaseStuck`)
- `gpu_lease_queue_depth` — queued holders
- `gpu_lease_acquisitions_total{kind}` — grants, by kind
- `gpu_lease_wait_seconds` — summary (count/sum) of queue wait times
- `gpu_lease_releases_total`, `gpu_lease_expirations_total` — how leases ended

Alerts: `GpuLeaseQueueSaturated` (queue depth > 3 for 15 min) and
`GpuLeaseStuck` (one holder active > 6 h). The "GPU Lease" panel on the
Grafana *AI Node Overview* dashboard shows the current holder and queue depth.

## Limits: what this is not

- **Not enforcement.** ollama and ComfyUI do not consult the arbiter today;
  only workloads you wrap (gpu-lock.sh, future integrations) participate.
  The README warning about simultaneous use still applies to unwrapped usage.
- **Not a VRAM allocator.** It serializes whole-GPU access; it does not
  partition memory between cooperative holders.

## Roadmap to hard enforcement

The obvious hard mode is a supervisor that watches leases and pauses/stops the
non-holder GPU container (`docker pause ai-comfyui`) so VRAM is actually
freed. That requires the Docker socket, which is **root-equivalent** on the
host — handing it to a network-reachable container would punch a hole
straight through the isolation model in `docs/AGENT_ISOLATION.md`. That trade
is deliberately not made here; if it ever is, it should be a host-side
systemd unit with a narrowly-scoped socket proxy, not a compose service.
