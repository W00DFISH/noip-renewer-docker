#!/bin/bash
# Self-update script — chạy bên trong container
# Gọi từ app.py khi user bấm Update

set -e

REPO_URL="${GITHUB_REPO:-https://github.com/W00DFISH/noip-renewer-docker}"
CONTAINER="${CONTAINER_NAME:-noip-renewer}"
WORK_DIR="/tmp/noip-update-$$"

echo "=== No-IP Renewer Self-Update ==="
echo "Repo: $REPO_URL"
echo "Container: $CONTAINER"

# Clone/pull latest code
echo "--- Pulling latest code from GitHub..."
if [ -d "$WORK_DIR" ]; then rm -rf "$WORK_DIR"; fi
git clone --depth=1 "$REPO_URL" "$WORK_DIR"

# Get new SHA
NEW_SHA=$(git -C "$WORK_DIR" rev-parse --short HEAD)
echo "New SHA: $NEW_SHA"

# Copy new files into /app (running container's workdir)
echo "--- Updating app files..."
cp "$WORK_DIR/app.py"          /app/app.py
cp "$WORK_DIR/requirements.txt" /app/requirements.txt
cp -r "$WORK_DIR/templates/"   /app/templates/

# Save new SHA to config
python3 -c "
import json, os
cfg_file = '/data/config.json'
try:
    cfg = json.load(open(cfg_file))
except:
    cfg = {}
cfg['current_sha'] = '$NEW_SHA'
json.dump(cfg, open(cfg_file,'w'), indent=2)
print('Saved SHA to config.')
"

# Cleanup
rm -rf "$WORK_DIR"

echo "--- Update complete! SHA: $NEW_SHA"
echo "=== Restarting container via Docker socket ==="

# Restart self via Docker socket
docker restart "$CONTAINER"
