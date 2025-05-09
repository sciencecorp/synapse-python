#!/bin/bash
set -e

SYNAPSE_APP_VERSION="0.1.0"
SYNAPSE_APP_EXE="{{APP_NAME}}"

SCRIPT_DIR=$(dirname "$0")
SOURCE_DIR="${SCRIPT_DIR}/../../"
# Check multiple possible build directories
BUILD_DIRS=(
    "${SOURCE_DIR}/build-aarch64/"
    "${SOURCE_DIR}/build/"
    "${SOURCE_DIR}/build-arm64/"
    "${SOURCE_DIR}/out/"
)

STAGING_DIR="/tmp/synapse-package"
mkdir -p ${STAGING_DIR}

# Binary install and setup
mkdir -p ${STAGING_DIR}/opt/scifi/bin

# Try to find the binary in various possible build directories
BINARY_FOUND=false
for BUILD_DIR in "${BUILD_DIRS[@]}"; do
    if [ -f "${BUILD_DIR}/${SYNAPSE_APP_EXE}" ]; then
        echo "Found binary at ${BUILD_DIR}/${SYNAPSE_APP_EXE}"
        cp "${BUILD_DIR}/${SYNAPSE_APP_EXE}" "${STAGING_DIR}/opt/scifi/bin/"
        BINARY_FOUND=true
        break
    fi
done

# If we didn't find the binary, try to find it anywhere in the source directory
if [ "$BINARY_FOUND" = false ]; then
    echo "Binary not found in standard build directories, searching source directory..."
    BINARY_PATH=$(find "${SOURCE_DIR}" -name "${SYNAPSE_APP_EXE}" -type f | grep -v "${STAGING_DIR}" | head -n 1)
    
    if [ -n "$BINARY_PATH" ]; then
        echo "Found binary at ${BINARY_PATH}"
        cp "${BINARY_PATH}" "${STAGING_DIR}/opt/scifi/bin/"
        BINARY_FOUND=true
    else
        echo "ERROR: Could not find binary ${SYNAPSE_APP_EXE} in any build directory!"
        exit 1
    fi
fi

# Launch script
mkdir -p ${STAGING_DIR}/opt/scifi/scripts
cp "${SCRIPT_DIR}/scripts/launch_synapse_app.sh" "${STAGING_DIR}/opt/scifi/scripts/"

# Systemd service install and setup
mkdir -p ${STAGING_DIR}/etc/systemd/system
cp "${SCRIPT_DIR}/systemd/${SYNAPSE_APP_EXE}.service" "${STAGING_DIR}/etc/systemd/system/"

# ---------------------------------------------------------------------------
# Copy application manifest so the device can reference it later
#   Destination: /opt/scifi/config/manifests/<APP_NAME>.json
# ---------------------------------------------------------------------------
MANIFEST_SRC="${SOURCE_DIR}/manifest.json"
if [ -f "${MANIFEST_SRC}" ]; then
    MANIFEST_DST_DIR="${STAGING_DIR}/opt/scifi/config/manifests"
    mkdir -p "${MANIFEST_DST_DIR}"
    cp "${MANIFEST_SRC}" "${MANIFEST_DST_DIR}/${SYNAPSE_APP_EXE}.json"
else
    echo "Warning: manifest.json not found at ${MANIFEST_SRC}; skipping copy."
fi

fpm -s dir -t deb \
    -n "${SYNAPSE_APP_EXE}" \
    -f \
    -v "${SYNAPSE_APP_VERSION}" \
    -C ${STAGING_DIR} \
    --deb-no-default-config-files \
    --depends "systemd" \
    --vendor "Science Corporation" \
    --description "Synapse Application" \
    --architecture arm64 \
    --after-install "${SCRIPT_DIR}/scripts/postinstall.sh" \
    --before-remove "${SCRIPT_DIR}/scripts/preremove.sh" \
    --after-remove "${SCRIPT_DIR}/scripts/postremove.sh" \
    . 