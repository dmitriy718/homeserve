"""
Homeserv Autonomous Fleet Supervisor Daemon — Hardened & GPU-Throttled Edition.
Orchestrates the 9 Autonomous Agents (3 Maintenance, 3 Cleanup, 3 Marketing) 24/7:
- Loopback-first local ComfyUI & ntfy endpoint resolution (zero hardcoded Wi-Fi LAN IPs).
- Aligned to the 3 Core Revenue Engines: PrintDeck.net, HorizonSVC.com, GigHound.net.
- Throttled GPU render cadence (8h Hero & 24h Masterpiece; 30m idle burn eliminated to save RTX 5060 wattage).
- Hourly public + local health & IndexNow checks and 4h backup/disk governance.
"""

import json
import os
import time
import urllib.request

from cleanup_agents import cleanup_agent_a, cleanup_agent_b, cleanup_agent_c
from gpu_queue import free_comfyui_memory, get_comfy_host
from maintenance_agents import maint_agent_a, maint_agent_b, maint_agent_c
from marketing_agents import MarketingFleetEngine

TRIGGER_FILE = "/srv/ai-node/data/comfyui/custom_nodes/site_host_hub/data/trigger.json"
STATE_FILE = "/srv/ai-node/data/agent_fleet/state.json"
RENDER_INTERVAL_SEC = int(os.environ.get("FLEET_RENDER_INTERVAL_SEC", "28800"))  # 8 hours

os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
marketing_engine = MarketingFleetEngine()


def check_external_triggers():
    if os.path.exists(TRIGGER_FILE):
        try:
            with open(TRIGGER_FILE, "r", encoding="utf-8") as f:
                tdata = json.load(f)
            os.remove(TRIGGER_FILE)
            site_id = tdata.get("site_id", "pulsegrid")
            cadence = tdata.get("cadence", "hero")
            print(f"\n[Trigger Watcher] ⚡ On-demand trigger received for {site_id} ({cadence.upper()})!")

            agent_map = {
                "pulsegrid": maint_agent_a,
                "autonomouse": maint_agent_b,
                "tradeloom": maint_agent_c,
            }
            if site_id in agent_map:
                pack = marketing_engine.produce_content_pack(site_id, cadence_type=cadence)
                agent_map[site_id].publish_content(pack)
                agent_map[site_id].verify_site_health()
        except Exception as te:
            print(f"[Trigger Watcher] Trigger execution notice: {te}")
            try:
                os.remove(TRIGGER_FILE)
            except Exception:
                pass


def wait_for_comfyui(timeout=60):
    """Probes local ComfyUI port 8188 until responsive."""
    comfy_host = get_comfy_host()
    print(f"[Fleet Supervisor] Probing local ComfyUI health on {comfy_host}...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(
                f"http://{comfy_host}/api/sites/status",
                headers={"User-Agent": "FleetSupervisor/3.1"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    print(f"✔ ComfyUI is online, operational, and responding on {comfy_host}.")
                    return True
        except Exception:
            pass
        time.sleep(2)
    print("⚠ ComfyUI probe timeout (continuing with health/governance supervision).")
    return False


def run_content_generation_cycle(cadence_type="hero"):
    """Coordinates Marketing -> ComfyUI -> Maintenance pipeline across the 3 Core Engines."""
    print("\n==========================================================================")
    print(f"🎬 TRIGGERING CONTENT CYCLE: [{cadence_type.upper()}] ACROSS 3 CORE ENGINES")
    print("==========================================================================")

    site_pairs = [
        ("pulsegrid", maint_agent_a),
        ("autonomouse", maint_agent_b),
        ("tradeloom", maint_agent_c),
    ]

    for site_id, maint_agent in site_pairs:
        try:
            print(f"\n[Fleet Supervisor] Launching production for {site_id} ({maint_agent.target_domain})...")
            pack = marketing_engine.produce_content_pack(site_id, cadence_type=cadence_type)
            maint_agent.publish_content(pack)
            maint_agent.verify_site_health()
        except Exception as e:
            print(f"[Fleet Supervisor] ✗ Cycle error for {site_id}: {e}")


def run_maintenance_health_cycle():
    """Runs synthetic DOM, asset audit, public health, and throttled public IndexNow checks."""
    print("\n[Fleet Supervisor] Running Maintenance Health Probes & Public Core Engine Checks...")
    maint_agent_a.audit_and_heal_assets(marketing_engine=None)
    maint_agent_b.audit_and_heal_assets(marketing_engine=None)
    maint_agent_c.audit_and_heal_assets(marketing_engine=None)
    h_a = maint_agent_a.verify_site_health()
    h_b = maint_agent_b.verify_site_health()
    h_c = maint_agent_c.verify_site_health()
    maint_agent_a._submit_indexnow_ping()
    maint_agent_b._submit_indexnow_ping()
    maint_agent_c._submit_indexnow_ping()
    return {"printdeck": h_a, "horizonsvc": h_b, "gighound": h_c}


def run_cleanup_backup_cycle():
    """Runs recordkeeping backups and disk governance."""
    print("\n[Fleet Supervisor] Running Cleanup & Storage Governance...")
    b_a = cleanup_agent_a.run_incremental_backup()
    b_b = cleanup_agent_b.run_incremental_backup()
    b_c = cleanup_agent_c.run_incremental_backup()
    d_a = cleanup_agent_a.check_disk_governance()
    return {"backups": {"printdeck": b_a, "horizonsvc": b_b, "gighound": b_c}, "disk": d_a}


def update_state(status_data):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=2)
    except Exception as e:
        print(f"State write error: {e}")


def main():
    comfy_host = get_comfy_host()
    print("==========================================================================")
    print("🚀 HOMESERV AUTONOMOUS AGENT FLEET DAEMON INITIALIZING (24/7 ONLINE)")
    print("   Core Engines: printdeck.net | horizonsvc.com | gighound.net")
    print(f"   Local ComfyUI Endpoint: http://{comfy_host} | Render Cadence: {RENDER_INTERVAL_SEC // 3600}h")
    print("==========================================================================")

    wait_for_comfyui()

    run_maintenance_health_cycle()
    run_cleanup_backup_cycle()

    last_hero_time = time.time()
    last_daily_time = time.time()
    last_health_time = time.time()
    last_cleanup_time = time.time()
    last_vram_purge = time.time()

    state = {
        "status": "online",
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "core_engines": ["printdeck.net", "horizonsvc.com", "gighound.net"],
        "render_interval_seconds": RENDER_INTERVAL_SEC,
        "agents": {
            "maintenance": ["maint-printdeck", "maint-horizonsvc", "maint-gighound"],
            "cleanup": ["cleanup-printdeck", "cleanup-horizonsvc", "cleanup-gighound"],
            "marketing": ["marketing-viral", "marketing-seo", "marketing-cro"],
        },
        "last_heartbeat": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    update_state(state)

    print("\n✔ Bootstrap complete. Entering 24/7 continuous autonomous supervisor loop (GPU throttled to 8h)...")

    while True:
        now = time.time()

        # 1. Throttled GPU Hero edition: every 8 hours (28,800s) — saves RTX 5060 idle wattage
        if now - last_hero_time >= RENDER_INTERVAL_SEC:
            print("\n[Scheduler] 8h Hero interval triggered.")
            run_content_generation_cycle(cadence_type="hero")
            free_comfyui_memory(unload_models=False, free_memory=True)
            last_hero_time = now

        # 2. Daily Masterpiece edition: every 24 hours
        if now - last_daily_time >= 86400:
            print("\n[Scheduler] Daily Masterpiece interval triggered.")
            run_content_generation_cycle(cadence_type="masterpiece")
            free_comfyui_memory(unload_models=False, free_memory=True)
            last_daily_time = now

        # 3. Hourly Maintenance Health & Public Domain Checks
        if now - last_health_time >= 3600:
            run_maintenance_health_cycle()
            last_health_time = now

        # 4. Cleanup & Backups: every 4 hours
        if now - last_cleanup_time >= 14400:
            run_cleanup_backup_cycle()
            last_cleanup_time = now

        # 5. Periodic VRAM defragmentation: every 8 hours
        if now - last_vram_purge >= 28800:
            print("\n[Scheduler] Routine PyTorch VRAM cache purge...")
            free_comfyui_memory(unload_models=False, free_memory=True)
            last_vram_purge = now

        state["last_heartbeat"] = time.strftime("%Y-%m-%d %H:%M:%S")
        update_state(state)
        check_external_triggers()
        time.sleep(5)


if __name__ == "__main__":
    main()
