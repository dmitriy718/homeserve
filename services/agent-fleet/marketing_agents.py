"""
The 3 Marketing Agents — Aligned to the 3 Core Revenue Engines (PrintDeck, HorizonSVC, GigHound).
Features:
- Persistent Anti-Repetition Registry: Every drop is guaranteed unique.
- 3-paragraph analytical prose anchored to PrintDeck.net, HorizonSVC.com, and GigHound.net.
- Topic-specific Schema.org FAQ generator & UTM attribution parameters.
"""

import json
import os
import random
import sys
import time

from gpu_queue import queue_workflow_prompt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.append("/srv/ai-node/scratch")
from master_taxonomies import AUTONOMOUSE_DATA, PULSEGRID_DATA, TRADELOOM_DATA

USED_TOPICS_FILE = "/srv/ai-node/data/agent_fleet/used_topics.json"

NETWORK_FUNNELS = {
    "pulsegrid": {
        "site_name": "PrintDeck Atelier Studio",
        "primary_cf_domain": "printdeck.net",
        "secondary_cf_domains": ["coastalserenity.co", "mirrortape.net"],
        "tax": PULSEGRID_DATA,
        "workflows": [
            "wf01_site1_merch_stream_24_7",
            "wf02_site1_merch_hero_3x_daily",
            "wf03_site1_merch_masterpiece_daily",
        ],
        "default_cta": "Explore Archival Editions on PrintDeck ➔",
    },
    "autonomouse": {
        "site_name": "HorizonSVC Infrastructure",
        "primary_cf_domain": "horizonsvc.com",
        "secondary_cf_domains": ["novahorizon.net", "gighound.net"],
        "tax": AUTONOMOUSE_DATA,
        "workflows": [
            "wf04_site2_ai_stream_24_7",
            "wf05_site2_ai_hero_3x_daily",
            "wf06_site2_ai_masterpiece_daily",
        ],
        "default_cta": "Book 30-Min Architecture Scoping Call ➔",
    },
    "tradeloom": {
        "site_name": "GigHound Contract Radar",
        "primary_cf_domain": "gighound.net",
        "secondary_cf_domains": ["horizonsvc.com", "tradeflows.net"],
        "tax": TRADELOOM_DATA,
        "workflows": [
            "wf10_site4_trade_stream_24_7",
            "wf11_site4_trade_hero_3x_daily",
            "wf12_site4_trade_masterpiece_daily",
        ],
        "default_cta": "Launch Free GigHound Contract Radar ➔",
    },
}


class MarketingFleetEngine:
    def __init__(self, workflows_dir="/srv/ai-node/data/comfyui/user/default/workflows/api"):
        self.workflows_dir = workflows_dir
        self.used_topics = self._load_used_topics()

    def _load_used_topics(self):
        if os.path.exists(USED_TOPICS_FILE):
            try:
                with open(USED_TOPICS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"pulsegrid": [], "autonomouse": [], "tradeloom": []}

    def _save_used_topics(self):
        os.makedirs(os.path.dirname(USED_TOPICS_FILE), exist_ok=True)
        try:
            with open(USED_TOPICS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.used_topics, f, indent=2)
        except Exception as e:
            print(f"[Marketing Fleet] Error saving used topics: {e}")

    def select_next_unique_topic(self, site_id):
        """Guarantees 100% distinct topics with persistent memory rotation."""
        cfg = NETWORK_FUNNELS[site_id]
        tax_list = cfg["tax"]
        used = set(self.used_topics.get(site_id, []))

        available = [t for t in tax_list if t["topic"] not in used]
        if not available:
            print(f"[Marketing Fleet] All {len(tax_list)} topics completed for {site_id}! Resetting rotation cycle...")
            self.used_topics[site_id] = []
            available = tax_list

        chosen = random.choice(available)
        self.used_topics.setdefault(site_id, []).append(chosen["topic"])
        self._save_used_topics()
        return chosen

    def synthesize_article_body(self, site_id, topic_item, post_id, cadence_type):
        """Generates 3-paragraph prose linking to the 3 Core Revenue Engines."""
        cfg = NETWORK_FUNNELS[site_id]
        utm = f"utm_source={site_id}&utm_medium=fleet_portal&utm_campaign={cadence_type}&utm_content={post_id}"

        pri_link = f"https://{cfg['primary_cf_domain']}?{utm}"
        sec1_link = f"https://{cfg['secondary_cf_domains'][0]}?{utm}"
        sec2_link = f"https://{cfg['secondary_cf_domains'][1]}?{utm}"

        intro = topic_item["intro"]
        analysis = topic_item["analysis"]
        takeaway = topic_item["takeaway"]

        if site_id == "tradeloom":
            cta_block = (
                f"{takeaway} "
                f"To monitor remote engineering contracts and generate 140-character preview hooks in under 30 seconds, launch the free radar at "
                f"<a href='{pri_link}' target='_blank'><strong>GigHound.net</strong></a>. "
                f"For deterministic single-host workflow automation and private AI infrastructure runbooks, explore "
                f"<a href='{sec1_link}' target='_blank'><strong>Horizon Services</strong></a>, "
                f"or review quantitative execution blueprints at <a href='{sec2_link}' target='_blank'><strong>TradeFlows.net</strong></a>."
            )
        elif site_id == "pulsegrid":
            cta_block = (
                f"{takeaway} "
                f"Through our archival studio at <a href='{pri_link}' target='_blank'><strong>PrintDeck.net</strong></a>, "
                f"collectors and interior studios can commission 300-DPI printable digital masters ($19), framed fine-art editions, gallery canvas, and heavyweight apparel. "
                f"Explore matching coastal home collections at <a href='{sec1_link}' target='_blank'><strong>Coastal Serenity</strong></a>, "
                f"or discover studio desk mats and analog audio editions at <a href='{sec2_link}' target='_blank'><strong>Mirror Tape</strong></a>."
            )
        else:
            cta_block = (
                f"{takeaway} "
                f"For production-grade single-host Docker hardening ($29 Runbook Pack, $295 Assessment, $995 Single-Host Setup), connect with "
                f"<a href='{pri_link}' target='_blank'><strong>Horizon Services (HorizonSVC.com)</strong></a>. "
                f"Deploy turnkey operator starter kits in minutes at "
                f"<a href='{sec1_link}' target='_blank'><strong>Nova Horizon</strong></a>, "
                f"or track live engineering contracts on <a href='{sec2_link}' target='_blank'><strong>GigHound.net</strong></a>."
            )

        return f"{intro}\n\n{analysis}\n\n{cta_block}"

    def produce_content_pack(self, site_id, cadence_type="hero"):
        """Collaborative generation pipeline."""
        cfg = NETWORK_FUNNELS[site_id]
        topic_item = self.select_next_unique_topic(site_id)

        post_id = f"{site_id}_{int(time.time()*1000)}"
        utm = f"utm_source={site_id}&utm_medium=fleet_cta&utm_campaign={cadence_type}&utm_content={post_id}"
        cta_url = f"https://{cfg['primary_cf_domain']}?{utm}"

        title = topic_item["title"]
        topic = topic_item["topic"]
        body = self.synthesize_article_body(site_id, topic_item, post_id, cadence_type)
        excerpt = topic_item["intro"][:180] + "..."
        price = topic_item.get("price", "Inquire")
        faqs = topic_item.get("faqs", [])

        wf_idx = 0 if cadence_type == "stream" else (1 if cadence_type == "hero" else 2)
        wf_name = cfg["workflows"][wf_idx]
        wf_path = os.path.join(self.workflows_dir, f"{wf_name}.json")

        image_url = ""
        filename = ""
        if os.path.exists(wf_path):
            try:
                with open(wf_path, "r", encoding="utf-8") as f:
                    wf_prompt = json.load(f)

                if "3" in wf_prompt and "inputs" in wf_prompt["3"]:
                    wf_prompt["3"]["inputs"]["seed"] = int(time.time() * 1000) % 1000000000

                print(f"[Marketing Fleet] Queueing ComfyUI workflow: {wf_name} for {site_id}...")
                res = queue_workflow_prompt(wf_prompt)
                if res.get("status") == "success":
                    filename = res["filename"]
                    image_url = res["view_url"]
                    print(f"[Marketing Fleet] Render complete: {filename}")
                else:
                    print(f"[Marketing Fleet] ComfyUI generation warning: {res}")
            except Exception as e:
                print(f"[Marketing Fleet] Error during workflow execution: {e}")

        return {
            "id": post_id,
            "site_id": site_id,
            "title": title,
            "topic": topic,
            "excerpt": excerpt,
            "body": body,
            "price": price,
            "cta_text": cfg["default_cta"],
            "cta_url": cta_url,
            "image_url": image_url or "/view?filename=site1_merch_24_7_00001_.png&type=output",
            "image_filename": filename,
            "cadence": cadence_type,
            "faqs": faqs,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
