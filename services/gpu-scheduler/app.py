"""Cooperative GPU lease arbiter for the single-GPU ai-node host.

ollama and comfyui both get `gpus: all` (compose/ai-node.yml) and nothing stops
them from allocating VRAM at the same time — concurrent use means silent
cudaMalloc failures. This service is the voluntary coordination point: clients
acquire an exclusive lease before GPU work and release it afterwards. It cannot
force uncooperative processes off the GPU; see docs/GPU_SCHEDULING.md for the
roadmap to hard enforcement.

No authentication: the container joins only the internal `ai`/`scrape` networks
(plus a 127.0.0.1-only publish for host tooling such as scripts/gpu-lock.sh),
holds no secrets, and only coordinates lease hints — API keys and models stay
in other services. The worst a network-local caller can do is disrupt
scheduling hints, never reach data.

State is in-memory on purpose: if the scheduler restarts, holders simply
re-acquire their leases (TTLs are short, heartbeats cheap), which beats
reviving stale leases after a crash.
"""
import os, threading, time
from typing import Literal, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

DEFAULT_TTL_SECONDS = int(os.getenv("GPU_LEASE_DEFAULT_TTL", "120"))
REAPER_INTERVAL_SECONDS = float(os.getenv("GPU_LEASE_REAPER_INTERVAL", "1"))

app = FastAPI(
    title="GPU Scheduler",
    version="1.0.0",
    description="Cooperative GPU lease arbiter.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Single condition variable guards all state below; every handler runs in the
# FastAPI threadpool and takes the lock, so one process is enough.
LOCK = threading.Condition()
LEASE: Optional[dict] = None  # holder, kind, ttl_seconds, acquired_at, last_heartbeat
QUEUE: list[dict] = []        # holder, kind, ttl_seconds, enqueued_at
ACQUISITIONS = {"llm": 0, "image": 0, "other": 0}
RELEASES = 0
EXPIRATIONS = 0
WAIT_COUNT = 0
WAIT_SUM = 0.0


class LeaseReq(BaseModel):
    holder: str = Field(..., min_length=1, max_length=64)
    kind: Literal["llm", "image", "other"] = "other"
    ttl_seconds: int = Field(DEFAULT_TTL_SECONDS, ge=1, le=86400)


def _grant_next_locked(now):
    global LEASE, WAIT_COUNT, WAIT_SUM
    if LEASE is None and QUEUE:
        nxt = QUEUE.pop(0)
        WAIT_COUNT += 1
        WAIT_SUM += now - nxt["enqueued_at"]
        ACQUISITIONS[nxt["kind"]] += 1
        LEASE = {
            "holder": nxt["holder"],
            "kind": nxt["kind"],
            "ttl_seconds": nxt["ttl_seconds"],
            "acquired_at": now,
            "last_heartbeat": now,
        }
        LOCK.notify_all()


def _expire_locked(now):
    """Reclaim the lease if the holder missed its TTL, then serve the queue."""
    global LEASE, EXPIRATIONS
    if LEASE and now - LEASE["last_heartbeat"] > LEASE["ttl_seconds"]:
        EXPIRATIONS += 1
        LEASE = None
        _grant_next_locked(now)


def _granted_payload():
    return {
        "granted": True,
        "holder": LEASE["holder"],
        "kind": LEASE["kind"],
        "ttl_seconds": LEASE["ttl_seconds"],
        "acquired_at": LEASE["acquired_at"],
        "queue_depth": len(QUEUE),
    }


def _conflict_payload(holder):
    position = next((i + 1 for i, q in enumerate(QUEUE) if q["holder"] == holder), len(QUEUE) + 1)
    return {
        "granted": False,
        "current_holder": LEASE["holder"] if LEASE else None,
        "queue_position": position,
        "queue_depth": len(QUEUE),
    }


@app.post("/leases")
def acquire(req: LeaseReq, wait: bool = Query(False), wait_timeout: float = Query(300, ge=1, le=3600)):
    """Take the exclusive lease, or queue for it.

    Without ?wait=true a conflict returns 409 with the caller's queue position.
    With ?wait=true the request long-polls (up to wait_timeout seconds) until
    the lease is granted to this holder, and returns 409 with timed_out=true if
    the deadline passes first. Re-acquiring a lease you already hold is an
    idempotent refresh.
    """
    global LEASE
    with LOCK:
        now = time.time()
        _expire_locked(now)
        if LEASE is None or LEASE["holder"] == req.holder:
            if LEASE is None:
                ACQUISITIONS[req.kind] += 1
                LEASE = {
                    "holder": req.holder,
                    "kind": req.kind,
                    "ttl_seconds": req.ttl_seconds,
                    "acquired_at": now,
                    "last_heartbeat": now,
                }
            else:
                LEASE.update(kind=req.kind, ttl_seconds=req.ttl_seconds, last_heartbeat=now)
            QUEUE[:] = [q for q in QUEUE if q["holder"] != req.holder]
            return _granted_payload()
        if all(q["holder"] != req.holder for q in QUEUE):
            QUEUE.append({"holder": req.holder, "kind": req.kind, "ttl_seconds": req.ttl_seconds, "enqueued_at": now})
        if not wait:
            raise HTTPException(409, detail=_conflict_payload(req.holder))
        deadline = now + wait_timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                detail = _conflict_payload(req.holder)
                detail["timed_out"] = True
                raise HTTPException(409, detail=detail)
            LOCK.wait(timeout=min(remaining, 1.0))
            now = time.time()
            _expire_locked(now)
            if LEASE and LEASE["holder"] == req.holder:
                return _granted_payload()


@app.delete("/leases/{holder}")
def release(holder: str):
    """Release the lease (and drop the holder from the queue if present)."""
    global LEASE, RELEASES
    with LOCK:
        now = time.time()
        _expire_locked(now)
        was_queued = any(q["holder"] == holder for q in QUEUE)
        QUEUE[:] = [q for q in QUEUE if q["holder"] != holder]
        if LEASE and LEASE["holder"] == holder:
            RELEASES += 1
            LEASE = None
            _grant_next_locked(now)
            return {"released": True, "was_queued": was_queued, "granted_to": LEASE["holder"] if LEASE else None}
        if was_queued:
            return {"released": False, "dequeued": True}
        raise HTTPException(404, "no lease or queue entry for holder")


@app.post("/leases/{holder}/heartbeat")
def heartbeat(holder: str):
    """Refresh the lease TTL; required at least once per ttl_seconds."""
    with LOCK:
        now = time.time()
        _expire_locked(now)
        if not LEASE or LEASE["holder"] != holder:
            raise HTTPException(404, "holder does not hold the lease")
        LEASE["last_heartbeat"] = now
        return {"holder": holder, "ttl_seconds": LEASE["ttl_seconds"], "expires_in_seconds": float(LEASE["ttl_seconds"])}


@app.get("/state")
def state():
    """Current holder, queue with positions, and lifetime counters."""
    with LOCK:
        now = time.time()
        _expire_locked(now)
        current = None
        if LEASE:
            current = {
                **LEASE,
                "expires_in_seconds": round(max(0.0, LEASE["ttl_seconds"] - (now - LEASE["last_heartbeat"])), 3),
            }
        return {
            "current": current,
            "queue": [
                {"position": i + 1, "holder": q["holder"], "kind": q["kind"], "waited_seconds": round(now - q["enqueued_at"], 3)}
                for i, q in enumerate(QUEUE)
            ],
            "history": {
                "acquisitions_total": dict(ACQUISITIONS),
                "releases_total": RELEASES,
                "expirations_total": EXPIRATIONS,
                "wait_samples": WAIT_COUNT,
            },
        }


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    with LOCK:
        _expire_locked(time.time())
        lines = [
            "# HELP gpu_lease_active Whether this holder currently holds the exclusive GPU lease.",
            "# TYPE gpu_lease_active gauge",
        ]
        if LEASE:
            labels = f'holder="{_escape(LEASE["holder"])}",kind="{_escape(LEASE["kind"])}"'
            lines.append(f"gpu_lease_active{{{labels}}} 1")
            lines += [
                "# HELP gpu_lease_started_unixtime Unix timestamp at which the current lease was granted.",
                "# TYPE gpu_lease_started_unixtime gauge",
                f"gpu_lease_started_unixtime{{{labels}}} {LEASE['acquired_at']:.3f}",
            ]
        lines += [
            "# HELP gpu_lease_queue_depth Number of holders waiting for the GPU lease.",
            "# TYPE gpu_lease_queue_depth gauge",
            f"gpu_lease_queue_depth {len(QUEUE)}",
            "# HELP gpu_lease_acquisitions_total GPU leases granted, by workload kind.",
            "# TYPE gpu_lease_acquisitions_total counter",
        ]
        for kind in ("llm", "image", "other"):
            lines.append(f'gpu_lease_acquisitions_total{{kind="{kind}"}} {ACQUISITIONS[kind]}')
        lines += [
            "# HELP gpu_lease_wait_seconds Time queued holders waited before being granted the lease.",
            "# TYPE gpu_lease_wait_seconds summary",
            f"gpu_lease_wait_seconds_count {WAIT_COUNT}",
            f"gpu_lease_wait_seconds_sum {WAIT_SUM:.6f}",
            "# HELP gpu_lease_releases_total GPU leases explicitly released by their holder.",
            "# TYPE gpu_lease_releases_total counter",
            f"gpu_lease_releases_total {RELEASES}",
            "# HELP gpu_lease_expirations_total GPU leases reclaimed after TTL expiry (holder crashed or stopped heartbeating).",
            "# TYPE gpu_lease_expirations_total counter",
            f"gpu_lease_expirations_total {EXPIRATIONS}",
        ]
        return "\n".join(lines) + "\n"


def _reaper():
    """Expire leases even when no requests arrive, so the queue keeps moving."""
    while True:
        with LOCK:
            LOCK.wait(timeout=REAPER_INTERVAL_SECONDS)
            _expire_locked(time.time())


threading.Thread(target=_reaper, daemon=True, name="gpu-lease-reaper").start()
