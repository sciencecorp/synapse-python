#!/bin/bash
set -e

# Detect architecture
ARCH=$(uname -m)
if [[ "${ARCH}" == "arm64" || "${ARCH}" == "aarch64" ]]; then
    TAG_SUFFIX="arm64"
else
    TAG_SUFFIX="amd64"
fi

# Get the app name from the directory name or manifest.json
APP_NAME=$(basename "$(pwd)")
if [ -f "manifest.json" ]; then
    # Try to extract the name from manifest.json
    if command -v jq &> /dev/null; then
        MANIFEST_NAME=$(jq -r '.name' manifest.json 2>/dev/null)
        if [ -n "$MANIFEST_NAME" ] && [ "$MANIFEST_NAME" != "null" ]; then
            APP_NAME=$MANIFEST_NAME
        fi
    fi
fi

# Image name
IMAGE="${APP_NAME}:latest-${TAG_SUFFIX}"

# Check if image exists
if ! docker image inspect $IMAGE >/dev/null 2>&1; then
  echo "Image $IMAGE not found. Please run build_docker.sh first."
  exit 1
fi

echo "Starting container for architecture: $ARCH"

# Run the container with appropriate mounts
# Adjust volume mappings as needed for your project
docker run -it \
  --rm \
  -v "$(pwd):/home/workspace" \
  $IMAGE 