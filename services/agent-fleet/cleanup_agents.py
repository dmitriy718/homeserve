"""
The 3 Cleanup & Recordkeeping Agents — Hardened & Resilient Edition.
Features:
- Complete standalone backups (packaging both JSON post data and generated PNG assets).
- Proactive disk governance with local ntfy push notifications.
- Automated rolling pruning (retaining last 10 snapshots).
- Automatic cleanup of ComfyUI temporary latent cache.
"""

import json
import os
import shutil
import time
import urllib.error
import urllib.request

from gpu_queue import get_ntfy_base_url

BACKUP_ROOT = "/srv/ai-node/data/backups/site_fleet"
COMFY_DATA_DIR = "/srv/ai-node/data/comfyui/custom_nodes/site_host_hub/data"
COMFY_OUTPUT_DIR = "/srv/ai-node/data/comfyui/output"


class CleanupAgent:
    def __init__(self, site_id, site_name, disk_threshold_pct=85.0):
        self.site_id = site_id
        self.site_name = site_name
        self.disk_threshold_pct = disk_threshold_pct
        self.backup_dir = os.path.join(BACKUP_ROOT, site_id)
        os.makedirs(self.backup_dir, exist_ok=True)

    def _send_ntfy_alert(self, title, message, priority="default", tags=None):
        """Sends push notification to local ntfy container."""
        try:
            ntfy_url = f"{get_ntfy_base_url()}/site_fleet_alerts"
            req = urllib.request.Request(
                ntfy_url,
                data=message.encode("utf-8"),
                headers={
                    "Title": title,
                    "Priority": priority,
                    "Tags": tags or "server,backup,warning",
                },
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            pass

    def run_incremental_backup(self):
        """Creates a standalone archive with posts and referenced image assets."""
        site_posts_dir = os.path.join(COMFY_DATA_DIR, self.site_id, "posts")
        if not os.path.exists(site_posts_dir):
            return {"status": "no_data"}

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        staging_dir = os.path.join(self.backup_dir, f".stage_{timestamp}")
        os.makedirs(os.path.join(staging_dir, "posts"), exist_ok=True)
        os.makedirs(os.path.join(staging_dir, "assets"), exist_ok=True)

        try:
            for f in os.listdir(site_posts_dir):
                if f.endswith(".json"):
                    src_f = os.path.join(site_posts_dir, f)
                    shutil.copy2(src_f, os.path.join(staging_dir, "posts", f))
                    try:
                        with open(src_f, "r", encoding="utf-8") as jf:
                            pdata = json.load(jf)
                            img_fn = pdata.get("image_filename")
                            if img_fn:
                                img_src = os.path.join(COMFY_OUTPUT_DIR, img_fn)
                                if os.path.exists(img_src):
                                    shutil.copy2(img_src, os.path.join(staging_dir, "assets", img_fn))
                    except Exception:
                        pass

            archive_name = f"backup_{self.site_id}_{timestamp}"
            dest_archive = os.path.join(self.backup_dir, archive_name)
            shutil.make_archive(dest_archive, "zip", staging_dir)
            zip_file = f"{dest_archive}.zip"
            fsize_kb = os.path.getsize(zip_file) / 1024
            print(f"[Cleanup-{self.site_id}] ✔ Standalone backup created: {os.path.basename(zip_file)} ({fsize_kb:.1f} KB)")

            shutil.rmtree(staging_dir, ignore_errors=True)

            try:
                web_backup_dir = os.path.join(COMFY_DATA_DIR, "backups", self.site_id)
                os.makedirs(web_backup_dir, exist_ok=True)
                shutil.copy2(zip_file, os.path.join(web_backup_dir, "latest.zip"))
            except Exception as be:
                print(f"[Cleanup-{self.site_id}] Notice mirroring latest backup: {be}")

            self._prune_old_backups(keep=10)
            return {"status": "success", "file": zip_file, "size_kb": fsize_kb}
        except Exception as e:
            shutil.rmtree(staging_dir, ignore_errors=True)
            print(f"[Cleanup-{self.site_id}] ✗ Backup error: {e}")
            return {"status": "error", "error": str(e)}

    def check_disk_governance(self):
        """Monitors filesystem storage. Dispatches ntfy alert if threshold exceeded."""
        try:
            total, used, free = shutil.disk_usage("/")
            used_pct = (used / total) * 100.0
            free_gb = free / (1024**3)
            print(f"[Cleanup-{self.site_id}] Disk Usage: {used_pct:.1f}% ({free_gb:.1f} GB free)")

            if used_pct >= self.disk_threshold_pct:
                msg = f"Homeserv storage alert! Usage at {used_pct:.1f}% ({free_gb:.1f} GB free). Triggering offsite sync..."
                print(f"[Cleanup-{self.site_id}] ⚠️ {msg}")
                self._send_ntfy_alert("Storage Threshold Exceeded", msg, priority="high", tags="warning,skull")
                self._trigger_offsite_backup()
                self._purge_old_scratch_files()
                return {"status": "threshold_exceeded", "used_pct": used_pct, "action": "offsite_backup_triggered"}

            return {"status": "ok", "used_pct": used_pct}
        except Exception as e:
            print(f"[Cleanup-{self.site_id}] Disk check error: {e}")
            return {"status": "error", "error": str(e)}

    def _trigger_offsite_backup(self):
        offsite_stage = os.path.join(BACKUP_ROOT, "offsite_staging")
        os.makedirs(offsite_stage, exist_ok=True)
        manifest_file = os.path.join(
            offsite_stage, f"offsite_manifest_{self.site_id}_{time.strftime('%Y%m%d%H%M%S')}.json"
        )
        manifest = {
            "site_id": self.site_id,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": self.backup_dir,
            "target": "cold_storage_vault",
            "files": [f for f in os.listdir(self.backup_dir) if f.endswith(".zip")],
        }
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"[Cleanup-{self.site_id}] Offsite sync bundle created: {os.path.basename(manifest_file)}")

    def _purge_old_scratch_files(self):
        temp_dir = os.path.join(COMFY_OUTPUT_DIR, "temp")
        if os.path.exists(temp_dir):
            for f in os.listdir(temp_dir):
                fp = os.path.join(temp_dir, f)
                if os.path.isfile(fp) and time.time() - os.path.getmtime(fp) > 86400 * 2:
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
        print(f"[Cleanup-{self.site_id}] Temporary latent cache pruned.")

    def _prune_old_backups(self, keep=10):
        backups = sorted([f for f in os.listdir(self.backup_dir) if f.endswith(".zip")])
        if len(backups) > keep:
            for b in backups[:-keep]:
                try:
                    os.remove(os.path.join(self.backup_dir, b))
                except Exception:
                    pass


# Initialize the 3 Cleanup Agents aligned to the 3 Core Engines
cleanup_agent_a = CleanupAgent("pulsegrid", "PrintDeck Atelier Studio")
cleanup_agent_b = CleanupAgent("autonomouse", "HorizonSVC Infrastructure")
cleanup_agent_c = CleanupAgent("tradeloom", "GigHound Contract Radar")
