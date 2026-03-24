#!/bin/bash
# Self-update via Portainer webhook
# Portainer GitOps watches the GitHub repo and redeploys automatically
# This script just triggers the webhook if configured

set -e
PORTAINER_WEBHOOK="${PORTAINER_WEBHOOK:-}"
REPO_URL="${GITHUB_REPO:-https://github.com/W00DFISH/noip-renewer-docker}"
CONTAINER="${CONTAINER_NAME:-noip-renewer}"
IMAGE="noip-renewer-web:local"
WORK_DIR="/tmp/noip-update-$$"

echo "=== No-IP Renewer Self-Update ==="
echo "Repo: $REPO_URL"

# Clone latest to check VERSION
echo "--- Checking latest version..."
git clone --depth=1 "$REPO_URL" "$WORK_DIR"
NEW_SHA=$(git -C "$WORK_DIR" rev-parse --short HEAD)
NEW_VER=$(cat "$WORK_DIR/VERSION" 2>/dev/null || echo "unknown")
echo "Latest: v$NEW_VER ($NEW_SHA)"

# If Portainer webhook configured, trigger it
if [ -n "$PORTAINER_WEBHOOK" ]; then
    echo "--- Triggering Portainer webhook..."
    curl -s -X POST "$PORTAINER_WEBHOOK" && echo "Webhook triggered!"
    # Save new SHA to config
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
    rm -rf "$WORK_DIR"
    echo "=== Portainer will rebuild and restart the stack ==="
    echo "=== Update triggered! v$NEW_VER ($NEW_SHA) ==="
    exit 0
fi

# Fallback: rebuild image manually
echo "--- No webhook configured, rebuilding image directly..."
cd "$WORK_DIR"

# Remove old image BEFORE building new one
echo "--- Removing old image tag..."
docker rmi "$IMAGE" --force 2>/dev/null && echo "Old image removed." || echo "No old image found."

# Build fresh
docker build --no-cache -t "$IMAGE" .
echo "--- Build complete!"

# Save SHA
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

rm -rf "$WORK_DIR"

echo "--- Recreating container with new image..."
# Write restart script to run outside this container
cat > /tmp/do_restart.sh << RESTART
#!/bin/sh
export DOCKER_API_VERSION=1.43
sleep 2
docker stop $CONTAINER 2>/dev/null || true
docker rm   $CONTAINER 2>/dev/null || true
docker run -d \
  --name $CONTAINER \
  -p 7895:7895 \
  -v noip_data:/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --restart unless-stopped \
  -e GITHUB_REPO="$REPO_URL" \
  -e CONTAINER_NAME="$CONTAINER" \
  $IMAGE
echo "=== New container started! v$NEW_VER ==="
docker image prune -f 2>/dev/null || true
RESTART

chmod +x /tmp/do_restart.sh
nohup docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /tmp/do_restart.sh:/do_restart.sh \
  -e DOCKER_API_VERSION=1.43 \
  docker:cli sh /do_restart.sh > /tmp/restart.log 2>&1 &

echo "[OK] Update complete! v$NEW_VER ($NEW_SHA)"
echo "=== Container will restart in ~5 seconds..."
