#!/bin/bash
# Self-update: pull latest code, rebuild image, start new container
# Uses nohup to detach from current container process before stopping it

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

# Rebuild image (always fresh, no cache)
echo "--- Rebuilding Docker image (no-cache)..."
cd "$WORK_DIR"
docker build --no-cache -t "$IMAGE" .
echo "--- Build complete!"

# Remove old/dangling images after successful build
echo "--- Cleaning up old images..."
docker image prune -f 2>/dev/null || true
# Force remove any untagged noip images
docker images --format "{{.ID}} {{.Repository}}:{{.Tag}}" | grep "noip-renewer" | grep -v "$IMAGE" | awk '{print $1}' | xargs -r docker rmi -f 2>/dev/null || true
echo "--- Build complete!"

# Save SHA + version to config
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

# Cleanup
rm -rf "$WORK_DIR"

echo "--- Starting new container (detached)..."

# Write a restart script that runs OUTSIDE this container
cat > /tmp/do_restart.sh << RESTART
#!/bin/bash
export DOCKER_API_VERSION=1.43
sleep 2
docker stop $CONTAINER 2>/dev/null || true
docker rm $CONTAINER 2>/dev/null || true
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
RESTART

chmod +x /tmp/do_restart.sh

# Run restart script detached via docker host — survives container stop
nohup docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /tmp/do_restart.sh:/do_restart.sh \
  -e DOCKER_API_VERSION=1.43 \
  docker:cli \
  sh /do_restart.sh > /tmp/restart.log 2>&1 &

echo "=== Update complete! v$NEW_VER ($NEW_SHA)"
echo "=== Container will restart in ~5 seconds..."
