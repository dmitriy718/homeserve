#!/usr/bin/env bash
# Apply the "no login by default" policy to apps whose auth toggle lives in
# their database rather than in compose configuration.
#
# Currently: Uptime Kuma. Kuma has no env var or config-file option for
# disableAuth (verified against the 2.5.0 server code — auth.js reads it only
# from the `setting` table), so it is upserted into kuma.db here. Idempotent;
# run any time, and once after the first Kuma start on a new install.
set -euo pipefail

kuma_db=/srv/ai-node/data/uptime-kuma/kuma.db

if [[ ! -f $kuma_db ]]; then
  echo "Kuma database not found at $kuma_db — start the stack once, then re-run."
  exit 1
fi

python3 - "$kuma_db" <<'EOF'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute(
    "INSERT INTO setting (key, value, type) VALUES ('disableAuth', 'true', 'boolean') "
    "ON CONFLICT(key) DO UPDATE SET value='true'"
)
db.commit()
print("disableAuth =", db.execute("select value from setting where key='disableAuth'").fetchone()[0])
db.close()
EOF

# Kuma caches settings in memory; restart if it is running so the change
# takes effect immediately.
if docker inspect -f '{{.State.Running}}' monitor-uptime-kuma 2>/dev/null | grep -q true; then
  docker restart monitor-uptime-kuma >/dev/null
  echo "monitor-uptime-kuma restarted"
fi
