# Optional apps (`apps/` overlays)

`apps/` holds **curated, optional app overlays**. They prove the
extensibility model: each one is a standalone compose file carrying the full
`homeserv.*` label contract from [APP_MANIFEST.md](APP_MANIFEST.md), so once
an app runs, the dashboard tile, Prometheus probe, health check, and backup
pause all pick it up automatically — no edits to `scripts/`, `monitoring/`,
or the base compose file.

Nothing here is installed or started by default, and nothing in the base
stack depends on these files. Enabling an app is always an explicit, opt-in
merge on the compose command line.

| App | Overlay | Legacy port | Subdomain (once routed) | Memory cap |
| --- | --- | ---: | --- | ---: |
| Jellyfin | `apps/jellyfin.yml` | 8096 | `jellyfin.` | 4 GiB |
| Immich | `apps/immich.yml` | 2283 | `immich.` | 5.25 GiB (4 containers) |
| Nextcloud | `apps/nextcloud.yml` | 8480 | `cloud.` | 1 GiB |

## Enabling an app

Always list the **base file first**, then the overlay(s):

```bash
cd /srv/ai-node
docker compose --env-file .env -f compose/ai-node.yml -f apps/jellyfin.yml up -d
```

Multiple apps at once:

```bash
docker compose --env-file .env \
  -f compose/ai-node.yml -f apps/jellyfin.yml -f apps/immich.yml up -d
```

Rules that make this work:

- **Base file first.** The project name `ai-node` comes from the top-level
  `name:` in `compose/ai-node.yml`. If you run an overlay alone, compose
  names the project after the directory and you get a second, disconnected
  stack. The label consumers (`backup.sh`, `health-check.sh`) filter on
  project `ai-node`, so a wrongly-named project is invisible to them.
- **Network merge.** The base file names its networks explicitly
  (`ai-node-ai`, `ai-node-monitoring`, `ai-node-scrape`). Overlays declare
  the same names with `external: true`: when the files merge, the networks
  match by key, and `external` records that the base stack owns their
  lifecycle. Consequence: **start the base stack at least once before
  enabling any overlay** — the networks must already exist.
  Apps sit on `monitoring` (so Caddy can proxy them) and `scrape` (so the
  blackbox exporter can probe them); they do not join the `ai` data plane.
- **No anchors across files.** The `x-common` YAML anchor in
  `compose/ai-node.yml` cannot be referenced from another file, so each
  overlay replicates its settings explicitly (restart policy,
  `no-new-privileges`, `pids_limit`, `init`, log rotation, healthcheck,
  `mem_limit`).
- **Image tags** are pinned and were verified against upstream releases on
  2026-08-30 (`jellyfin/jellyfin:10.11.11`,
  `ghcr.io/immich-app/immich-server:v3.1.0` + `immich-machine-learning:v3.1.0`
  + `ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0`
  + `redis:7-alpine`, `nextcloud:33-apache`). The first `pull` verifies them
  for real; if a tag ever fails to resolve, check the project's releases page
  and bump the pin deliberately.

After the first `up`, refresh discovery so probes and the dashboard tile
appear immediately (it also runs automatically on every stack start):

```bash
/srv/ai-node/scripts/discover-services.sh
```

## Caddy routes (opt-in, like the apps)

The overlays cannot touch `config/caddy/Caddyfile` (and must not — an app
you never enabled would leave a dead route). Add one site block per enabled
app, following the existing protected-route pattern (`import sso` puts the
app behind Authelia like the other UIs):

```caddy
jellyfin.{$BASE_DOMAIN:homeserve.lan} {
	tls internal
	import sso
	reverse_proxy jellyfin:8096
}

immich.{$BASE_DOMAIN:homeserve.lan} {
	tls internal
	import sso
	reverse_proxy immich-server:2283
}

cloud.{$BASE_DOMAIN:homeserve.lan} {
	tls internal
	import sso
	reverse_proxy nextcloud:80
}
```

Then reload Caddy (the Caddyfile is bind-mounted into the container):

```bash
sudo docker exec edge-caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Notes:

- All three apps keep their own account layer on top of SSO (same posture as
  Open WebUI and Grafana).
- Immich mobile-app uploads work through the proxy fine; if you ever set an
  upload size limit, do it in Immich, not Caddy (Caddy has no default body
  limit).
- Nextcloud CalDAV/CardDAV auto-discovery (`.well-known/caldav`) is not
  routed — configure clients with the full DAV URL if needed.

## Jellyfin (`apps/jellyfin.yml`)

- **First run:** open `http://LAN_IP:8096` (or `https://jellyfin.<BASE_DOMAIN>`
  once routed) and complete the setup wizard — it creates the admin account
  and the first libraries. Media is mounted read-only at `/media` from
  `MEDIA_ROOT` (default `/srv/media`).
- **Data:** config/cache in `/srv/ai-node/data/jellyfin`.
- **Hardware transcoding:** a commented `gpus: all` block is in the overlay.
  Enable it only with the NVIDIA container toolkit in place (installed by
  `scripts/install.sh` when a GPU is detected), then enable NVENC in the
  Jellyfin dashboard. Intel QSV does not apply to this host.
- Probe: `http://jellyfin:8096/health` (Jellyfin's built-in health endpoint).

## Immich (`apps/immich.yml`)

Four containers: `immich-server` (the only labeled, proxied, published one),
`immich-machine-learning`, `immich-postgres`, `immich-redis`. The database is
Immich's own Postgres build with the VectorChord extension — a plain
`postgres` or `pgvector` image will not work.

- **Secrets first.** Before the first `up`:
  ```bash
  cp apps/immich.env.example secrets/immich.env
  # replace DB_PASSWORD with: openssl rand -hex 16
  ```
  Set `DB_PASSWORD` once, before first start — changing it later does not
  re-provision the initialized database.
- **First run:** open `http://LAN_IP:2283` and register — the first account
  becomes the admin. Point the mobile app's backup at the same URL (or the
  `immich.` subdomain).
- **Data:** uploads/thumbnails `/srv/ai-node/data/immich/upload`, database
  `/srv/ai-node/data/immich/postgres`, ML model cache
  `/srv/ai-node/data/immich/model-cache`.
- A commented read-only `MEDIA_ROOT` mount is included if you want Jellyfin's
  library browsable as an Immich external library.
- Probe: `http://immich-server:2283/api/server/ping` (the v1.118+ endpoint;
  the older `/api/server-info/ping` is gone in v3). If a probe ever goes red
  after a major Immich upgrade, re-check the path against the release notes.

## Nextcloud (`apps/nextcloud.yml`)

Single container, Apache variant, **SQLite** (no DB service to keep it
simple — fine for a few users; a Postgres move is documented in the overlay
as future work).

- **First run:** open `http://LAN_IP:8480` and create the admin account.
  `NEXTCLOUD_TRUSTED_DOMAINS` is pre-set to `cloud.<BASE_DOMAIN>` plus both
  legacy `IP:8480` addresses, so both front-door and legacy access work.
- **Data:** everything (including the SQLite DB) in
  `/srv/ai-node/data/nextcloud`.
- Background jobs default to AJAX; for regular use, add a host cron entry:
  `*/5 * * * * root docker exec -u www-data app-nextcloud php cron.php`
- `OVERWRITEPROTOCOL=https` is deliberately **not** set — it would redirect
  legacy `http://…:8480` access to HTTPS that nothing serves. Revisit if you
  unpublish the legacy port.
- Probe: `http://nextcloud:80/status.php`.

## Data and backups

`scripts/backup.sh` archives `/srv/ai-node` (and `/srv/repos`) wholesale, so
**all app data under `/srv/ai-node/data/<app>/` is included automatically** —
nothing to configure.

`MEDIA_ROOT` (`/srv/media`) is **not** covered. To back the media library up
too, archive it separately, e.g.:

```bash
sudo tar --zstd -cpf /srv/backups/local/media-$(date -u +%Y%m%dT%H%M%SZ).tar.zst -C /srv media
```

### Backup pausing

All three overlays carry `homeserv.backup.pause: "true"`. `scripts/backup.sh`
discovers pause candidates by that label and pauses containers **by ID**, so
overlay services are covered automatically even though they are not defined
in the base compose file.

## Updates

`scripts/update-stack.sh` (and therefore `deploy.sh`) detects the active set
of compose files from the running containers' own labels, so enabled overlays
are pulled, rebuilt, and kept through `up -d --remove-orphans` automatically.
If app containers were ever created with a different file set (or while the
base stack was down), bring them back with a merged `up -d`:

```bash
cd /srv/ai-node
docker compose --env-file .env -f compose/ai-node.yml -f apps/jellyfin.yml pull
docker compose --env-file .env -f compose/ai-node.yml -f apps/jellyfin.yml up -d
```

(Include every enabled `-f apps/*.yml` in the `up -d` so all apps are
recreated in one go.) The same merged command also updates an app's images
independently of the base stack.

## Resource budget

`mem_limit` values are caps, not reservations, but they are the right
planning numbers on this 16 GiB host:

| App | Containers | Combined cap |
| --- | --- | ---: |
| Jellyfin | 1 | 4 GiB |
| Immich | server 2 GiB + ML 2 GiB + postgres 1 GiB + redis 256 MiB | 5.25 GiB |
| Nextcloud | 1 | 1 GiB |
| **All three** | | **~10.25 GiB** |

The base stack's own caps already exceed physical RAM on paper (Ollama and
ComfyUI alone are 16 GiB of caps), and Jellyfin transcodes and Immich ML jobs
are exactly the workloads that spike toward their caps. **Do not enable all
three apps at once without watching memory**: enable one, run its heaviest
job (a transcode, an ML scan), and check `docker stats` / the Grafana host
dashboard before enabling the next. If pressure shows, lower the app caps in
the overlay before lowering anything in the base stack.
