#!/bin/bash
# Deploy the ops API to bolls:/opt/miles-ops (docker compose, 127.0.0.1:8791, behind nginx /ops/api/).
#   ./deploy.sh            build context rsync + docker compose up -d --build + health check
#   ./deploy.sh --check    also run the classification unit check locally first
#   ./deploy.sh --logs     tail container logs
# First-time setup of the read-only DB role + .env: ssh bolls 'bash -s' < setup_db_role.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
HOST=${HOST:-bolls}
DEST=/opt/miles-ops
if [ "${1:-}" = "--logs" ]; then exec ssh "$HOST" "cd $DEST && docker compose logs -f --tail=100"; fi
if [ "${1:-}" = "--check" ]; then "$HERE/.venv/bin/python" "$HERE/tests/check_classification.py"; fi

STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/src/geo" "$STAGE/src/model"
cp -R "$HERE/app" "$STAGE/src/"; find "$STAGE/src/app" -name __pycache__ -prune -exec rm -rf {} +
cp "$HERE/Dockerfile" "$HERE/requirements.txt" "$STAGE/src/"
for f in berlin_geo.pkl.gz paid_zones.geojson replay_berlin_2024-06.npz replay_meta.json cells_berlin.json demand_berlin.npz; do cp "$HERE/geo/$f" "$STAGE/src/geo/"; done
for f in stranding_gbm.joblib stranding_meta.json tabpfn_context.npz tabpfn_meta.json; do cp "$HERE/../model/$f" "$STAGE/src/model/"; done

ssh "$HOST" "test -s $DEST/.env" || { echo "missing $DEST/.env: run setup_db_role.sh first" >&2; exit 1; }
rsync -az --delete --checksum "$STAGE/src/" "$HOST:$DEST/src/"
rsync -az --checksum "$HERE/compose.yml" "$HOST:$DEST/compose.yml"
ssh "$HOST" "cd $DEST && mkdir -p data && docker compose up -d --build 2>&1 | tail -5"

echo "waiting for health..."
for i in $(seq 1 60); do
  if out=$(ssh "$HOST" "curl -fsS --max-time 3 http://127.0.0.1:8791/health" 2>/dev/null); then
    echo "local:  $out" | cut -c1-300; break
  fi
  sleep 2
  [ "$i" = 60 ] && { echo "health check failed" >&2; ssh "$HOST" "cd $DEST && docker compose logs --tail=40"; exit 1; }
done
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://miles.bolls.dev/ops/api/health || true)
echo "public: https://miles.bolls.dev/ops/api/health -> HTTP $code"
