"""
The 3 Maintenance Agents — Core Engine Alignment & Public IndexNow Edition.
Features:
- Publishes content bundles to local ComfyUI Site Host with retry resilience.
- Multi-channel syndication broadcast via local ntfy (/site_fleet_feed).
- Public-domain-only IndexNow verification & pinging for printdeck.net, horizonsvc.com, and gighound.net
  (strictly blocks private/RFC1918/Tailscale/.local URLs from ever being sent to api.indexnow.org).
- Autonomic Dead-Asset Self-Healing Sentinel & Synthetic Health Probes across local + public Core Engines.
"""

import ipaddress
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from gpu_queue import get_comfy_host, get_ntfy_base_url

PUBLIC_CORE_DOMAINS = ("horizonsvc.com", "gighound.net", "printdeck.net")
INDEXNOW_KEY = os.environ.get("PARA_INDEXNOW_KEY", "e8f4c2a19b3d7e5a0c6f1b4d8a2e7c9f")
INDEXNOW_STATE_FILE = "/srv/ai-node/data/agent_fleet/indexnow_last_ping.json"
INDEXNOW_MIN_INTERVAL_SEC = 28800  # Max 1 ping per 8 hours per public domain

COMFY_DATA_DIR = "/srv/ai-node/data/comfyui/custom_nodes/site_host_hub/data"
COMFY_OUTPUT_DIR = "/srv/ai-node/data/comfyui/output"


def is_public_indexable_url(url: str) -> bool:
    """Return True ONLY for HTTPS URLs on verified public domains (never localhost, .local, or private/Tailscale IPs)."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            return False
        host = (parsed.hostname or "").lower().strip()
        if not host or host == "localhost" or host.endswith((".local", ".internal", ".lan")):
            return False
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
            # Explicitly block Carrier-Grade NAT / Tailscale 100.64.0.0/10
            if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
                return False
        except ValueError:
            pass
        return host in PUBLIC_CORE_DOMAINS
    except Exception:
        return False


class MaintenanceAgent:
    def __init__(self, site_id, site_name, target_domain):
        self.site_id = site_id
        self.site_name = site_name
        self.target_domain = target_domain

    def _should_ping_domain(self, domain: str) -> bool:
        try:
            if os.path.exists(INDEXNOW_STATE_FILE):
                with open(INDEXNOW_STATE_FILE, "r", encoding="utf-8") as fh:
                    st = json.load(fh)
                last_ts = float(st.get(domain, 0))
                if time.time() - last_ts < INDEXNOW_MIN_INTERVAL_SEC:
                    return False
        except Exception:
            pass
        return True

    def _record_domain_ping(self, domain: str) -> None:
        try:
            os.makedirs(os.path.dirname(INDEXNOW_STATE_FILE), exist_ok=True)
            st = {}
            if os.path.exists(INDEXNOW_STATE_FILE):
                with open(INDEXNOW_STATE_FILE, "r", encoding="utf-8") as fh:
                    st = json.load(fh)
            st[domain] = time.time()
            with open(INDEXNOW_STATE_FILE, "w", encoding="utf-8") as fh:
                json.dump(st, fh, indent=2)
        except Exception:
            pass

    def _submit_indexnow_ping(self, permalink=None):
        """Verifies public Core Engine health and submits ONLY public HTTPS URLs to IndexNow."""
        if permalink and not is_public_indexable_url(permalink):
            print(f"[Maintenance-{self.site_id}] Skipped private/local permalink for IndexNow; checking public domain {self.target_domain}.")

        domain = self.target_domain.lower().strip()
        if domain not in PUBLIC_CORE_DOMAINS:
            return
        if not self._should_ping_domain(domain):
            return

        public_root = f"https://{domain}/"
        public_llms = f"https://{domain}/llms.txt"
        key_loc = f"https://{domain}/{INDEXNOW_KEY}.txt"

        try:
            # Verify live 200 OK on public domain root before pinging IndexNow
            probe_req = urllib.request.Request(public_root, headers={"User-Agent": "Mozilla/5.0 (Homeserv-HealthCheck/3.1)"})
            with urllib.request.urlopen(probe_req, timeout=6) as pr:
                if pr.status != 200:
                    return

            url_list = [u for u in (public_root, public_llms) if is_public_indexable_url(u)]
            if not url_list:
                return

            payload = {
                "host": domain,
                "key": INDEXNOW_KEY,
                "keyLocation": key_loc,
                "urlList": url_list,
            }
            req = urllib.request.Request(
                "https://api.indexnow.org/indexnow",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": "Homeserv-IndexNow/2.0",
                },
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status in (200, 202):
                    self._record_domain_ping(domain)
                    print(f"[Maintenance-{self.site_id}] ⚡ IndexNow ping dispatched for https://{domain}/ (HTTP {resp.status}).")
        except Exception:
            pass

    def _dispatch_syndication_broadcast(self, pack):
        """Broadcasts newly published drops to local ntfy feed."""
        try:
            comfy_host = get_comfy_host()
            ntfy_feed_url = f"{get_ntfy_base_url()}/site_fleet_feed"
            pid = pack.get("id")
            title = pack.get("title", "New Drop")
            price = pack.get("price", "")
            img_fn = pack.get("image_filename", "")
            permalink = f"http://{comfy_host}/sites/{self.site_id}/post/{pid}"
            thumb_url = f"http://{comfy_host}/sites/thumb/{img_fn}?w=600" if img_fn else ""

            body_text = (
                f"✨ [{self.site_name}] New {pack.get('cadence', 'hero').upper()} drop!\n"
                f"{title}\n\nEngine: https://{self.target_domain}/\nPrice/Terms: {price}\nLocal Feed: {permalink}"
            )

            headers = {
                "Title": f"[{self.site_name}] {title[:40]}...",
                "Priority": "default",
                "Tags": "sparkles,art,robot",
                "Click": f"https://{self.target_domain}/",
            }
            if thumb_url:
                headers["Attach"] = thumb_url

            req = urllib.request.Request(ntfy_feed_url, data=body_text.encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=5):
                print(f"[Maintenance-{self.site_id}] 📡 Syndication broadcast sent to local ntfy feed.")
        except Exception:
            pass

    def publish_content(self, content_pack, max_retries=2):
        """Uploads content package to ComfyUI Native Site Host with retries and triggers syndication & public IndexNow."""
        comfy_host = get_comfy_host()
        payload = {"site_id": self.site_id, "post": content_pack}
        data = json.dumps(payload).encode("utf-8")

        for attempt in range(1, max_retries + 1):
            try:
                req = urllib.request.Request(
                    f"http://{comfy_host}/api/sites/publish",
                    data=data,
                    headers={"Content-Type": "application/json", "User-Agent": "Homeserv-Maintenance/3.1"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    print(f"[Maintenance-{self.site_id}] ✔ Published {content_pack['id']} to {self.site_name}")

                    self._dispatch_syndication_broadcast(content_pack)
                    self._submit_indexnow_ping(f"https://{self.target_domain}/")
                    return res
            except Exception as e:
                print(f"[Maintenance-{self.site_id}] Publish attempt {attempt} failed: {e}")
                if attempt == max_retries:
                    return {"error": str(e)}
                time.sleep(2)

    def audit_and_heal_assets(self, marketing_engine=None):
        """Audits post assets. Only heals missing assets if referenced file is absent."""
        posts_dir = os.path.join(COMFY_DATA_DIR, self.site_id, "posts")
        if not os.path.exists(posts_dir):
            return {"status": "no_posts"}

        healed_count = 0
        for pf in os.listdir(posts_dir):
            if pf.endswith(".json"):
                fpath = os.path.join(posts_dir, pf)
                try:
                    with open(fpath, "r", encoding="utf-8") as jf:
                        pdata = json.load(jf)

                    img_fn = pdata.get("image_filename")
                    asset_ok = False
                    if img_fn:
                        img_path = os.path.join(COMFY_OUTPUT_DIR, img_fn)
                        if os.path.exists(img_path) and os.path.getsize(img_path) > 1000:
                            asset_ok = True
                    elif pdata.get("image_url"):
                        asset_ok = True

                    if not asset_ok and marketing_engine and healed_count < 1:
                        print(f"[Maintenance-{self.site_id}] ⚠️ Missing asset for {pf}! Initiating self-healing...")
                        fresh_pack = marketing_engine.produce_content_pack(
                            self.site_id, cadence_type=pdata.get("cadence", "hero")
                        )
                        if fresh_pack.get("image_filename"):
                            pdata["image_filename"] = fresh_pack["image_filename"]
                            pdata["image_url"] = fresh_pack["image_url"]
                            with open(fpath, "w", encoding="utf-8") as jf:
                                json.dump(pdata, jf, indent=2)
                            healed_count += 1
                            print(f"[Maintenance-{self.site_id}] ✔ Healed {pf} with fresh asset: {fresh_pack['image_filename']}")
                except Exception as e:
                    print(f"[Maintenance-{self.site_id}] Audit error on {pf}: {e}")

        return {"healed": healed_count}

    def verify_site_health(self):
        """Deep synthetic DOM, local portal, and public Core Engine health audit."""
        comfy_host = get_comfy_host()
        base_url = f"http://{comfy_host}/sites/{self.site_id}"
        public_url = f"https://{self.target_domain}/"
        report = {
            "site_id": self.site_id,
            "target_domain": self.target_domain,
            "url": base_url,
            "public_url": public_url,
            "http_status": None,
            "public_http_status": None,
            "sitemap_ok": False,
            "rss_ok": False,
            "outbound_link_present": False,
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        try:
            req = urllib.request.Request(base_url, headers={"User-Agent": "Homeserv-Health-Probe/3.1"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                report["http_status"] = resp.status
                html_body = resp.read().decode("utf-8", errors="ignore")
                if any(dom in html_body for dom in PUBLIC_CORE_DOMAINS):
                    report["outbound_link_present"] = True
        except Exception as e:
            report["http_status"] = f"ERROR: {e}"

        try:
            pub_req = urllib.request.Request(public_url, headers={"User-Agent": "Mozilla/5.0 (Homeserv-Health-Probe/3.1)"})
            with urllib.request.urlopen(pub_req, timeout=8) as pub_resp:
                report["public_http_status"] = pub_resp.status
        except Exception as e:
            report["public_http_status"] = f"ERROR: {e}"

        try:
            req = urllib.request.Request(f"{base_url}/sitemap.xml", headers={"User-Agent": "Homeserv-Health-Probe/3.1"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    report["sitemap_ok"] = True
        except Exception:
            pass

        try:
            req = urllib.request.Request(f"{base_url}/rss.xml", headers={"User-Agent": "Homeserv-Health-Probe/3.1"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    report["rss_ok"] = True
        except Exception:
            pass

        status_flag = "PASSED" if (report["http_status"] == 200 and report["public_http_status"] == 200) else "WARNING"
        print(
            f"[Maintenance-{self.site_id}] Health check {status_flag} "
            f"(Local HTTP {report['http_status']} | Public {self.target_domain} HTTP {report['public_http_status']}) "
            f"| Backlinks: {report['outbound_link_present']} | Sitemap: {report['sitemap_ok']} | RSS: {report['rss_ok']}"
        )
        return report


# Initialize the 3 Maintenance Agents aligned to the 3 Core Revenue Engines
maint_agent_a = MaintenanceAgent("pulsegrid", "PrintDeck Atelier Studio", "printdeck.net")
maint_agent_b = MaintenanceAgent("autonomouse", "HorizonSVC Infrastructure", "horizonsvc.com")
maint_agent_c = MaintenanceAgent("tradeloom", "GigHound Contract Radar", "gighound.net")
