# Service map

LAN address: `192.168.1.68`  
Tailscale address: `100.65.105.46`

| Service | Purpose | Container | Port | LAN URL | Tailscale URL | Persistent Data | GPU | Health Check |
|---|---|---|---:|---|---|---|---|---|
| Ollama | LLM inference API | `ai-ollama` | 11434 | `http://192.168.1.68:11434` | `http://100.65.105.46:11434` | `/srv/models/ollama` | Yes | `/api/tags` |
| Open WebUI | Ollama chat UI | `ai-open-webui` | 3000 | `http://192.168.1.68:3000` | `http://100.65.105.46:3000` | `/srv/ai-node/data/open-webui` | Via Ollama | `/health` |
| Embeddings | MiniLM OpenAI-compatible embeddings | `ai-embeddings` | 8081 | `http://192.168.1.68:8081` | `http://100.65.105.46:8081` | `/srv/models/embeddings` | No (CPU) | `/health` |
| ComfyUI | Image workflow UI/API | `ai-comfyui` | 8188 | `http://192.168.1.68:8188` | `http://100.65.105.46:8188` | `/srv/models/comfyui`, `/srv/ai-node/data/comfyui` | Yes | `/system_stats` |
| Prometheus | Metrics and network-probe history | `monitor-prometheus` | 9091 | `http://192.168.1.68:9091` | `http://100.65.105.46:9091` | `/srv/ai-node/data/prometheus` | No | `/-/ready` |
| Grafana | Provisioned dashboards | `monitor-grafana` | 3001 | `http://192.168.1.68:3001` | `http://100.65.105.46:3001` | `/srv/ai-node/data/grafana` | No | `/api/health` |
| Node Exporter | Host metrics (internal only) | `monitor-node-exporter` | 9100 internal | Not exposed | Not exposed | None | No | `/metrics` internally |
| NVIDIA Exporter | GPU utilization/VRAM/temp/power (internal only) | `monitor-nvidia-exporter` | 9400 internal | Not exposed | Not exposed | None | Yes | `/metrics` internally |
| Blackbox Exporter | ICMP, DNS, and HTTP probes (internal only) | `monitor-blackbox` | 9115 internal | Not exposed | Not exposed | None | No | Prometheus targets |
| Uptime Kuma | User-managed uptime UI | `monitor-uptime-kuma` | 3002 | `http://192.168.1.68:3002` | `http://100.65.105.46:3002` | `/srv/ai-node/data/uptime-kuma` | No | `/` |
| Speedtest Tracker | Daily Internet performance history | `monitor-speedtest` | 8765 | `http://192.168.1.68:8765` | `http://100.65.105.46:8765` | `/srv/ai-node/data/speedtest` | No | `/` |
| Playwright | Disposable browser verification | profile-only `dev-playwright-test` | None | Not exposed | Not exposed | Image/config only | No | `test.js` exit status |

The pre-existing Nextcloud, Wekan, and Prometheus-snap workloads were preserved and are not managed by this Compose project.
