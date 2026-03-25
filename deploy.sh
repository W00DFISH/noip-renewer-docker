#!/bin/bash
# Initial deployment script
# Run this ONCE via SSH to set up the container as standalone
# After this, use the web UI to update

set -e
REPO_URL="https://github.com/W00DFISH/noip-renewer-docker"
IMAGE="noip-renewer-web:local"
CONTAINER="noip-renewer"
WORK_DIR="/tmp/noip-deploy-$$"

echo "=== No-IP Renewer — Initial Deploy ==="

# Clone repo
echo "--- Cloning repo..."
git clone --depth=1 "$REPO_URL" "$WORK_DIR"
cd "$WORK_DIR"

# Build image
echo "--- Building image..."
docker build -t "$IMAGE" .

# Stop/remove existing container if any
docker stop "$CONTAINER" 2>/dev/null || true
docker rm   "$CONTAINER" 2>/dev/null || true

# Run as standalone (NOT via docker compose)
echo "--- Starting container..."
docker run -d \
  --name "$CONTAINER" \
  -p 7895:7895 \
  -v noip_data:/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --restart unless-stopped \
  -e GITHUB_REPO="$REPO_URL" \
  -e CONTAINER_NAME="$CONTAINER" \
  --log-driver json-file \
  --log-opt max-size=2m \
  --log-opt max-file=3 \
  "$IMAGE"

# Cleanup
rm -rf "$WORK_DIR"
docker image prune -f 2>/dev/null || true

echo "=== Done! Open http://$(hostname -I | awk '{print $1}'):7895 ==="
