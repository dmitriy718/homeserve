"""
GPU Queue & Concurrency Manager for ComfyUI on Homeserv.
Hardened & Resilient Edition:
- Local loopback-first endpoint resolution (127.0.0.1 -> local Tailscale 100.65.105.46).
- Single-flight mutex serialization for RTX 5060 (8 GB VRAM).
- Pre-flight ComfyUI queue inspection (avoids colliding with manual web UI jobs).
- Fail-fast error detection from ComfyUI execution history.
- Network retry logic with exponential backoff.
- VRAM defragmentation and PyTorch cache cleanup via /free.
"""

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_LOCK = threading.Lock()


def resolve_local_endpoint(port: int, env_var: str = "") -> str:
    """Prefer 127.0.0.1:<port> locally on homeserv; fall back to local Tailscale interface 100.65.105.46:<port>."""
    if env_var and os.environ.get(env_var):
        return os.environ[env_var].strip()
    for host in ("127.0.0.1", "100.65.105.46"):
        try:
            with socket.create_connection((host, port), timeout=0.6):
                return f"{host}:{port}"
        except OSError:
            continue
    return f"127.0.0.1:{port}"


def get_comfy_host() -> str:
    return resolve_local_endpoint(8188, "COMFY_HOST")


def get_ntfy_base_url() -> str:
    return f"http://{resolve_local_endpoint(2586, 'NTFY_HOST')}"


def check_queue_idle(max_wait=30):
    """Checks if ComfyUI is currently processing external jobs; waits if busy."""
    url = f"http://{get_comfy_host()}/queue"
    start = time.time()
    while time.time() - start < max_wait:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Homeserv-GPUQueue/2.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                qdata = json.loads(resp.read().decode("utf-8"))
                running = len(qdata.get("queue_running", []))
                if running == 0:
                    return True
                time.sleep(2)
        except Exception:
            return True
    return False


def free_comfyui_memory(unload_models=False, free_memory=True):
    """Triggers ComfyUI's internal memory manager to release cached VRAM."""
    url = f"http://{get_comfy_host()}/free"
    payload = json.dumps({"unload_models": unload_models, "free_memory": free_memory}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5):
            print("[GPU Queue] ✔ VRAM PyTorch cache purge triggered successfully.")
            return True
    except Exception as e:
        print(f"[GPU Queue] VRAM cache purge notice: {e}")
        return False


def queue_workflow_prompt(prompt_dict, timeout=180, max_retries=3):
    """Submits a workflow to ComfyUI with pre-flight check, fail-fast status, and retries."""
    comfy_host = get_comfy_host()
    with _LOCK:
        check_queue_idle(max_wait=20)

        p = {"prompt": prompt_dict}
        data = json.dumps(p).encode("utf-8")
        prompt_id = None

        for attempt in range(1, max_retries + 1):
            try:
                req = urllib.request.Request(
                    f"http://{comfy_host}/prompt",
                    data=data,
                    headers={"Content-Type": "application/json", "User-Agent": "Homeserv-GPUQueue/2.0"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    prompt_id = res.get("prompt_id")
                    if prompt_id:
                        break
            except Exception as e:
                print(f"[GPU Queue] Prompt submission attempt {attempt} failed: {e}")
                if attempt == max_retries:
                    return {"status": "error", "error": f"Failed after {max_retries} attempts: {e}"}
                time.sleep(2 * attempt)

        if not prompt_id:
            return {"status": "error", "error": "No prompt_id returned by ComfyUI"}

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                req = urllib.request.Request(
                    f"http://{comfy_host}/history/{prompt_id}",
                    headers={"User-Agent": "Homeserv-GPUQueue/2.0"},
                )
                with urllib.request.urlopen(req, timeout=10) as h_resp:
                    hist = json.loads(h_resp.read().decode("utf-8"))
                    if prompt_id in hist:
                        item = hist[prompt_id]
                        status_info = item.get("status", {})
                        if status_info.get("status_str") == "error":
                            messages = status_info.get("messages", [])
                            print(f"[GPU Queue] ✗ ComfyUI reported execution error: {messages}")
                            return {"status": "error", "error": messages, "prompt_id": prompt_id}

                        outputs = item.get("outputs", {})
                        for _nid, nout in outputs.items():
                            if "images" in nout and len(nout["images"]) > 0:
                                img_info = nout["images"][0]
                                filename = img_info["filename"]
                                subfolder = img_info.get("subfolder", "")
                                img_type = img_info.get("type", "output")
                                return {
                                    "status": "success",
                                    "prompt_id": prompt_id,
                                    "filename": filename,
                                    "subfolder": subfolder,
                                    "type": img_type,
                                    "view_url": f"/view?filename={filename}&subfolder={subfolder}&type={img_type}",
                                }
            except Exception:
                pass

            time.sleep(2)

        return {"status": "timeout", "prompt_id": prompt_id}
