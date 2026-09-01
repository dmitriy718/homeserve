# App manifest: compose labels as the source of truth

Adding a service to this stack used to mean hand-editing seven places: the
compose file, `SERVICE_MAP.md`, the Prometheus blackbox targets, the health
check URL list, the backup pause list, the Grafana dashboard, and the README.
The app-manifest model makes the **compose labels the single source of truth**;
probes, health checks, and backup pauses derive from them automatically (the
dashboard tile is the one manual exception — see below).

## Label contract

Labels live on the service definition in `compose/ai-node.yml`:

| Label | Meaning | Absent means |
| --- | --- | --- |
| `homeserv.name` | Display name (e.g. `"Open WebUI"`). Marks the container as part of the manifest. | Not a managed app; ignored by discovery |
| `homeserv.purpose` | One-liner shown on the dashboard tile | Empty purpose |
| `homeserv.subdomain` | Caddy subdomain of `BASE_DOMAIN` (e.g. `"webui"` → `https://webui.homeserve.lan`) | Not proxied |
| `homeserv.legacy.port` | Published direct-access port on `LAN_IP` (e.g. `"3000"`) | No legacy port; no host-side health check or legacy link |
| `homeserv.probe.url` | Container-internal HTTP URL for blackbox probing (e.g. `"http://open-webui:8080/health"`). Must be reachable from the `scrape` network. | No Prometheus probe |
| `homeserv.backup.pause` | `"true"` to pause the service while `scripts/backup.sh` archives | Not paused |

Rules of thumb:

- User-facing apps get all applicable labels.
- Infra (exporters, Caddy, Alertmanager, LLDAP) gets `name`/`purpose` for
  documentation value only — no `subdomain`/`legacy.port`, so no tile, no
  probe, no pause.
- `homeserv.subdomain` records the Caddy subdomain for documentation and
  link-building; it no longer drives the dashboard (tiles are a static
  catalog in `services/dashboard/index.html`). An admin backend that should
  stay off the dashboard (LLDAP) simply gets no tile there.
- A probe URL must point at a DNS name reachable from the `blackbox-exporter`
  container (the `scrape` network). ntfy, for example, is only on
  `monitoring`, so it carries no `homeserv.probe.url`.

## How discovery flows

```
compose/ai-node.yml labels
        │
        ▼
scripts/discover-services.sh          (docker ps + docker inspect, jq)
        │
        └──► monitoring/targets.d/probes.json  ──► Prometheus job
                 (file_sd target groups)              blackbox_http_file_sd
```

The dashboard is **not** part of discovery: tiles come from a static
`GROUPS` catalog in `services/dashboard/index.html`, and the status dots
probe same-origin `/healthz/<key>` routes defined in
`config/caddy/Caddyfile`. Adding an app to the dashboard is a manual edit
to those two files (see the worked example below).

The same labels are read directly at runtime by:

- `scripts/health-check.sh` — probes `http://LAN_IP:<legacy.port><probe path>`
  for each container with `homeserv.probe.url` + `homeserv.legacy.port`.
  Falls back to a built-in static list when Docker is unreachable or no
  labels are found (e.g. before the stack exists at boot).
- `scripts/backup.sh` — pauses every running container labeled
  `homeserv.backup.pause=true`. Falls back to the previous static list when
  Docker or the labels are unavailable.

`discover-services.sh` runs automatically on every stack start
(`ExecStartPost` in `host/etc/systemd/system/ai-node-stack.service`, after
the healthy-wait). It is safe to run any time and refuses to touch the
generated files when Docker is unreachable.

## Generated files

| Host path | Consumer | Mount |
| --- | --- | --- |
| `/srv/ai-node/monitoring/targets.d/probes.json` | Prometheus `file_sd_configs` (`/etc/prometheus/targets.d/*.json`) | `monitoring/targets.d` → `/etc/prometheus/targets.d:ro` |

It is generated — do not edit or commit it. Prometheus picks up `file_sd`
changes without a restart. (`services/dashboard/services.json` used to be
generated here too; the dashboard no longer fetches it.)

## Adding a new app: worked example (Jellyfin)

The compose block below is now the *only* edit needed for probes, health
checks, and backup pauses. The dashboard tile is a manual step on top: add
it to the `GROUPS` catalog in `services/dashboard/index.html` (a
`/healthz/<key>` handle for the status dot already exists for the three
curated apps; a *new* app also needs one in `config/caddy/Caddyfile`).
(`SERVICE_MAP.md` and the README remain worth updating for humans, but
nothing breaks if you lag.)

```yaml
  jellyfin:
    <<: *common
    image: jellyfin/jellyfin:10.11.11
    container_name: media-jellyfin
    labels:
      homeserv.name: "Jellyfin"
      homeserv.purpose: "Movies and shows, self-hosted"
      homeserv.subdomain: "jellyfin"
      homeserv.legacy.port: "8096"
      homeserv.probe.url: "http://jellyfin:8096/health"
      homeserv.backup.pause: "true"
    volumes:
      - /srv/ai-node/data/jellyfin:/config
      - /srv/media:/media:ro
    ports:
      - "${LAN_IP}:8096:8096"
      - "${TAILSCALE_IP}:8096:8096"
    mem_limit: 4g
    networks: [monitoring, scrape]
```

Plus what labels cannot express: the dashboard tile (see above) and — for a
**new** subdomain — a site block in `config/caddy/Caddyfile` (the
`jellyfin.`, `immich.`, and `cloud.` blocks already exist and answer 502
until their overlay runs). Metrics beyond blackbox probing need nothing —
the probe label covers it.

Then refresh:

```bash
# Manual refresh (also runs automatically on stack start):
/srv/ai-node/scripts/discover-services.sh
```

Label changes take effect on the next stack restart
(`systemctl restart ai-node-stack`) or a manual run of the script. Prometheus
reloads the file_sd targets itself; health-check and backup read labels live
on each run.

## What you no longer edit when adding a service

- `monitoring/prometheus.yml` — blackbox HTTP targets come from
  `targets.d/probes.json` (the static `blackbox_http` job remains only as a
  pre-discovery fallback).
- `scripts/health-check.sh` — URL list derives from labels.
- `scripts/backup.sh` — pause list derives from labels.

What you still edit: the compose service itself (with labels), the dashboard
tile (`GROUPS` in `services/dashboard/index.html`, plus a `/healthz/<key>`
handle in the Caddyfile if the tile should show a status dot), the Caddyfile
site block for a new subdomain, and prose docs (`SERVICE_MAP.md`,
`README.md`) for human readers.
