#!/bin/bash
# Self-update: pull latest code, rebuild image, restart container

set -e
export DOCKER_API_VERSION=1.43   # Fix: match Synology NAS Docker daemon version

REPO_URL="${GITHUB_REPO:-https://github.com/W00DFISH/noip-renewer-docker}"
CONTAINER="${CONTAINER_NAME:-noip-renewer}"
WORK_DIR="/tmp/noip-update-$$"

echo "=== No-IP Renewer Self-Update ==="
echo "Repo: $REPO_URL"

echo "--- Cloning latest code..."
git clone --depth=1 "$REPO_URL" "$WORK_DIR"
NEW_SHA=$(git -C "$WORK_DIR" rev-parse --short HEAD)
NEW_VER=$(cat "$WORK_DIR/VERSION" 2>/dev/null || echo "unknown")
echo "Latest SHA: $NEW_SHA | Version: $NEW_VER"

echo "--- Rebuilding Docker image..."
cd "$WORK_DIR"
docker build -t noip-renewer-web:local .
echo "--- Build complete!"

# Save SHA + version to config
python3 -c "
import json
cfg_file='/data/config.json'
try: cfg=json.load(open(cfg_file))
except: cfg={}
cfg['current_sha']='$NEW_SHA'
cfg['current_version']='$NEW_VER'
json.dump(cfg,open(cfg_file,'w'),indent=2)
print('Saved SHA: $NEW_SHA, Version: $NEW_VER')
"

rm -rf "$WORK_DIR"

echo "--- Restarting container: $CONTAINER"
docker restart "$CONTAINER"
echo "=== Update complete! v$NEW_VER ($NEW_SHA) ==="
