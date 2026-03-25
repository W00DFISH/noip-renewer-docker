#!/bin/bash
# Self-update: pull latest code, rebuild image, recreate container
# Container runs STANDALONE (not via Portainer stack)
# This ensures Portainer does NOT interfere with the new container

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

# Save SHA to config BEFORE rebuild
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

# Build new image
echo "--- Building new image..."
cd "$WORK_DIR"
docker build -t "${IMAGE}:new" .
echo "--- Build complete!"

# Cleanup clone
rm -rf "$WORK_DIR"

# Write restart script — runs OUTSIDE current container via docker:cli
# This script: stops old, retags image, removes old image, starts new container
cat > /tmp/do_restart.sh << RESTART
#!/bin/sh
export DOCKER_API_VERSION=1.43
sleep 2

echo "--- Stopping old container..."
docker stop $CONTAINER 2>/dev/null || true
docker rm   $CONTAINER 2>/dev/null || true

echo "--- Removing old image..."
docker rmi ${IMAGE} 2>/dev/null || true

echo "--- Tagging new image..."
docker tag ${IMAGE}:new ${IMAGE}
docker rmi ${IMAGE}:new 2>/dev/null || true

echo "--- Starting new container (standalone)..."
docker run -d \
  --name $CONTAINER \
  -p 7895:7895 \
  -v noip_data:/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --restart unless-stopped \
  -e GITHUB_REPO="$REPO_URL" \
  -e CONTAINER_NAME="$CONTAINER" \
  --log-driver json-file \
  --log-opt max-size=2m \
  --log-opt max-file=3 \
  ${IMAGE}

echo "--- Cleaning up dangling images..."
docker image prune -f 2>/dev/null || true

echo "=== Done! v$NEW_VER ($NEW_SHA) ==="
RESTART

chmod +x /tmp/do_restart.sh

# Run restart script via docker:cli (survives this container being stopped)
echo "--- Launching restart sequence..."
nohup docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /tmp/do_restart.sh:/do_restart.sh \
  -e DOCKER_API_VERSION=1.43 \
  docker:cli \
  sh /do_restart.sh > /tmp/restart.log 2>&1 &

echo "[OK] Update complete! v$NEW_VER ($NEW_SHA)"
echo "=== Container will restart in ~5 seconds..."
