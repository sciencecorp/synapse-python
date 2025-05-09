#!/bin/bash
set -e

# App name variable that will be replaced
SYNAPSE_APP_EXE="{{APP_NAME}}"

# Set up and reload udev rules
udevadm control --reload-rules
udevadm trigger

# Set permissions for the executable
chown root:root /opt/scifi/bin/"${SYNAPSE_APP_EXE}"
chmod 755 /opt/scifi/bin/"${SYNAPSE_APP_EXE}"

# Reload and start the service
systemctl daemon-reload
