#!/bin/bash
# Self-update: pull latest code, rebuild image, recreate container
# Key: container stops itself LAST, new container takes over

set -e
export DOCKER_API_VERSION=1.43

REPO_URL="${GITHUB_REPO:-https://github.com/W00DFISH/noip-renewer-docker}"
CONTAINER="${CONTAINER_NAME:-noip-renewer}"
IMAGE="noip-renewer-web:local"
WORK_DIR="/tmp/noip-update-$$"

echo "=== No-IP Renewer Self-Update ==="
echo "Repo: $REPO_URL"

# Clone latest
echo "--- Cloning latest code..."
git clone --depth=1 "$REPO_URL" "$WORK_DIR"
NEW_SHA=$(git -C "$WORK_DIR" rev-parse --short HEAD)
NEW_VER=$(cat "$WORK_DIR/VERSION" 2>/dev/null || echo "unknown")
echo "Latest: v$NEW_VER ($NEW_SHA)"

# Rebuild image
echo "--- Rebuilding Docker image..."
cd "$WORK_DIR"
docker build -t "$IMAGE" .
echo "--- Build complete!"

# Save SHA + version to config volume
python3 -c "
import json
cfg='/data/config.json'
try: c=json.load(open(cfg))
except: c={}
c['current_sha']='$NEW_SHA'
c['current_version']='$NEW_VER'
json.dump(c,open(cfg,'w'),indent=2)
print('Config saved.')
"

# Cleanup clone
rm -rf "$WORK_DIR"

# Get current container port/volume config to recreate identically
echo "--- Recreating container..."
docker stop "$CONTAINER" || true
docker rm "$CONTAINER" || true
docker run -d \
  --name "$CONTAINER" \
  -p 7895:7895 \
  -v noip_data:/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --restart unless-stopped \
  -e GITHUB_REPO="$REPO_URL" \
  -e CONTAINER_NAME="$CONTAINER" \
  "$IMAGE"

echo "=== Done! v$NEW_VER ($NEW_SHA) — container restarted ==="
