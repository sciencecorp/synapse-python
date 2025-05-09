#!/bin/bash
# Launches app
# Will need to be run as root
# We might be able to get away with this as a normal user using CAP_SYS_NICE and CAP_SYS_RESOURCE, but we'll need to test
# TODO: this should be configurable
SYNAPSE_APP_EXE="{{APP_NAME}}"
MANIFEST_FILE="/opt/scifi/config/app_manifest.json"

# Set max UDP write buffer size to 4MB
sysctl -w net.core.wmem_max=4194304
sysctl -w net.core.wmem_default=4194304

# Set up LD_LIBRARY_PATH to prefer our local libraries and user libraries
export LD_LIBRARY_PATH=/opt/scifi/usr-libs:/opt/scifi/lib:$LD_LIBRARY_PATH

# Launch the server
export SCIFI_ROOT=${SCIFI_ROOT:-/opt/scifi}
PATH_TO_EXE="$SCIFI_ROOT/bin/${SYNAPSE_APP_EXE}"
if [ ! -x "${PATH_TO_EXE}" ]; then
    echo "Server binary not found or not executable" >&2
    exit 1
fi

exec "${PATH_TO_EXE}" "$@" 