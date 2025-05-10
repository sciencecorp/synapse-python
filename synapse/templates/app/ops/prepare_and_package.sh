#!/usr/bin/env bash
set -e

# ---------------------------------------------------------------------------
# prepare_and_package.sh
# ---------------------------------------------------------------------------
# This script copies the shared *ops* template directory to a temporary working
# location, replaces placeholder tokens with the supplied application name, and
# then runs the main `package.sh` script so that a Debian package is produced.
#
# Usage (inside the Docker packaging container):
#   /synapse_ops/prepare_and_package.sh <APP_NAME>
# ---------------------------------------------------------------------------

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <APP_NAME>" >&2
  exit 1
fi

APP_NAME="$1"

# The template directory is mounted read-only by the CLI.  Work on a copy so we
# can make in-place edits while preserving the pristine original.
TEMPLATE_DIR="/synapse_ops"
TEMP_DIR="/tmp/synapse_package_ops"
rm -rf "$TEMP_DIR"
cp -r "$TEMPLATE_DIR" "$TEMP_DIR"

# Replace all occurrences of the placeholder token in every file of the copied
# template directory.
find "$TEMP_DIR" -type f -exec sed -i "s/{{APP_NAME}}/${APP_NAME}/g" {} +

# The systemd service file itself has the placeholder in its *filename* so we
# need to rename it as well.
SERVICE_TEMPLATE="$TEMP_DIR/package/systemd/{{APP_NAME}}.service"
if [[ -f "$SERVICE_TEMPLATE" ]]; then
  mv "$SERVICE_TEMPLATE" "$TEMP_DIR/package/systemd/${APP_NAME}.service"
fi

# The main packaging script expects SOURCE_DIR to point at the application
# workspace mounted from the host.  Ensure the variable is set correctly and
# that the script is executable.
chmod +x "$TEMP_DIR/package/package.sh"
sed -i 's|SOURCE_DIR=.*|SOURCE_DIR="/home/workspace"|' "$TEMP_DIR/package/package.sh"

# Kick off the actual `.deb` creation process.
cd /home/workspace
bash "$TEMP_DIR/package/package.sh" 