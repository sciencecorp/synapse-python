#!/bin/bash
set -e

# App name from manifest.json or directory name
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

# Detect architecture
ARCH=$(uname -m)
if [[ "${ARCH}" == "arm64" || "${ARCH}" == "aarch64" ]]; then
    CONTAINER_TAG="arm64"
    PLATFORM="linux/arm64"
    DOCKERFILE_PATH="ops/docker/Dockerfile.arm64"
else
    CONTAINER_TAG="amd64"
    PLATFORM="linux/amd64"
    DOCKERFILE_PATH="ops/docker/Dockerfile"
fi

# Image names
SDK_IMAGE="${APP_NAME}:latest-${CONTAINER_TAG}"

echo "Building for architecture: $ARCH"
echo "Application name: $APP_NAME"

# Build the SDK image
docker build -t $SDK_IMAGE -f "${DOCKERFILE_PATH}" .

echo "Successfully built $SDK_IMAGE"

# Check if the binary exists, and if not, try to build it
if [ ! -f "build/${APP_NAME}" ] && [ ! -f "build-aarch64/${APP_NAME}" ] && [ ! -f "build-arm64/${APP_NAME}" ]; then
    echo "Binary not found, attempting to build it in Docker..."
    # Try to build the binary in Docker
    docker run --rm \
        -v "$(pwd):/home/workspace" \
        $SDK_IMAGE \
        /bin/bash -c "cd /home/workspace && \
                      mkdir -p build && \
                      cd build && \
                      cmake .. && \
                      make -j$(nproc)"
                      
    # Check if build succeeded
    if [ -f "build/${APP_NAME}" ]; then
        echo "Binary built successfully at build/${APP_NAME}"
    else
        echo "Warning: Could not automatically build binary. Make sure it's available before packaging."
    fi
else
    echo "Binary already exists, skipping build step."
fi 