#!/bin/bash
set -e

# App name variable that will be replaced
SYNAPSE_APP_EXE="{{APP_NAME}}"

# Stop and disable the service
systemctl stop "${SYNAPSE_APP_EXE}" || true
systemctl disable "${SYNAPSE_APP_EXE}" || true 