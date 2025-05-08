#!/usr/bin/env python3

import os
import shutil
import argparse
import json
from pathlib import Path

def setup_app_structure(app_dir, app_name):
    """Setup the basic application structure"""
    print(f"Setting up app structure for {app_name} in {app_dir}")
    
    # Create app directory if it doesn't exist
    if not os.path.exists(app_dir):
        os.makedirs(app_dir)
    
    # Get the template directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = script_dir
    
    # Copy necessary scripts
    scripts = [
        'build_docker.sh',
        'start_docker.sh',
        'package.sh'
    ]
    
    for script in scripts:
        source = os.path.join(template_dir, script)
        destination = os.path.join(app_dir, script)
        
        if os.path.exists(source):
            shutil.copy(source, destination)
            # Make the script executable
            os.chmod(destination, 0o755)
            print(f"Copied {script} to {destination}")
    
    # Create ops directory structure
    ops_dir = os.path.join(app_dir, 'ops')
    os.makedirs(os.path.join(ops_dir, 'docker'), exist_ok=True)
    os.makedirs(os.path.join(ops_dir, 'package'), exist_ok=True)
    os.makedirs(os.path.join(ops_dir, 'package', 'scripts'), exist_ok=True)
    os.makedirs(os.path.join(ops_dir, 'package', 'systemd'), exist_ok=True)
    
    # Create deploy directory and copy deploy script
    deploy_dir = os.path.join(app_dir, 'deploy')
    os.makedirs(deploy_dir, exist_ok=True)
    
    # Copy deploy scripts
    deploy_source = os.path.join(template_dir, 'deploy')
    for item in os.listdir(deploy_source):
        source_item = os.path.join(deploy_source, item)
        dest_item = os.path.join(deploy_dir, item)
        
        if os.path.isfile(source_item):
            shutil.copy(source_item, dest_item)
            # Make scripts executable
            if item.endswith('.py') or item.endswith('.sh'):
                os.chmod(dest_item, 0o755)
            print(f"Copied {item} to {dest_item}")
    
    # Create basic package script
    package_script = os.path.join(ops_dir, 'package', 'package.sh')
    with open(package_script, 'w') as f:
        f.write(f'''#!/bin/bash

SYNAPSE_APP_VERSION="0.1.0"
SYNAPSE_APP_EXE="{app_name}"

SCRIPT_DIR=$(dirname "$0")
SOURCE_DIR="${{SCRIPT_DIR}}/../../"
BUILD_DIR="${{SOURCE_DIR}}/build-aarch64/"

STAGING_DIR="/tmp/synapse-package"
mkdir -p ${{STAGING_DIR}}

# Binary install and setup
# TODO: Decide if there is a better place to put this
mkdir -p ${{STAGING_DIR}}/opt/scifi/bin
cp "${{BUILD_DIR}}/${{SYNAPSE_APP_EXE}}" "${{STAGING_DIR}}/opt/scifi/bin/"

# Launch script
mkdir -p ${{STAGING_DIR}}/opt/scifi/scripts
cp "${{SCRIPT_DIR}}/scripts/launch_app.sh" "${{STAGING_DIR}}/opt/scifi/scripts/"

# Systemd service install and setup
mkdir -p ${{STAGING_DIR}}/etc/systemd/system
cp "${{SCRIPT_DIR}}/systemd/{app_name}.service" "${{STAGING_DIR}}/etc/systemd/system/"

fpm -s dir -t deb \\
    -n "${{SYNAPSE_APP_EXE}}" \\
    -f \\
    -v "${{SYNAPSE_APP_VERSION}}" \\
    -C ${{STAGING_DIR}} \\
    --deb-no-default-config-files \\
    --depends "systemd" \\
    --vendor "Science Corporation" \\
    --description "Synapse Application" \\
    --architecture arm64 \\
    --after-install "${{SCRIPT_DIR}}/scripts/postinstall.sh" \\
    --before-remove "${{SCRIPT_DIR}}/scripts/preremove.sh" \\
    --after-remove "${{SCRIPT_DIR}}/scripts/postremove.sh" \\
    .
''')
    os.chmod(package_script, 0o755)
    
    # Create basic systemd service file
    service_file = os.path.join(ops_dir, 'package', 'systemd', f'{app_name}.service')
    with open(service_file, 'w') as f:
        f.write(f'''[Unit]
Description={app_name} service
After=network.target

[Service]
ExecStart=/opt/scifi/scripts/launch_app.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
''')
    
    # Create launch script
    launch_script = os.path.join(ops_dir, 'package', 'scripts', 'launch_app.sh')
    with open(launch_script, 'w') as f:
        f.write(f'''#!/bin/bash
set -e

# Launch the application
/opt/scifi/bin/{app_name}
''')
    os.chmod(launch_script, 0o755)
    
    # Create post-install script
    postinstall_script = os.path.join(ops_dir, 'package', 'scripts', 'postinstall.sh')
    with open(postinstall_script, 'w') as f:
        f.write(f'''#!/bin/bash
set -e

# Enable and start the service
systemctl daemon-reload
systemctl enable {app_name}.service
systemctl start {app_name}.service

echo "{app_name} installed and started successfully"
''')
    os.chmod(postinstall_script, 0o755)
    
    # Create pre-remove script
    preremove_script = os.path.join(ops_dir, 'package', 'scripts', 'preremove.sh')
    with open(preremove_script, 'w') as f:
        f.write(f'''#!/bin/bash
set -e

# Stop and disable the service
systemctl stop {app_name}.service
systemctl disable {app_name}.service

echo "Stopped {app_name} service"
''')
    os.chmod(preremove_script, 0o755)
    
    # Create post-remove script
    postremove_script = os.path.join(ops_dir, 'package', 'scripts', 'postremove.sh')
    with open(postremove_script, 'w') as f:
        f.write(f'''#!/bin/bash
set -e

# Reload systemd to remove the service
systemctl daemon-reload

echo "Removed {app_name} service"
''')
    os.chmod(postremove_script, 0o755)
    
    # Create basic Dockerfiles
    dockerfile = os.path.join(ops_dir, 'docker', 'Dockerfile')
    with open(dockerfile, 'w') as f:
        f.write('''FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

# Install base dependencies
RUN apt-get update && apt-get install -y \\
    build-essential \\
    cmake \\
    pkg-config \\
    git \\
    ruby-dev \\
    curl \\
    jq \\
    && gem install fpm

# Add a non-root user
RUN useradd -ms /bin/bash developer
USER developer
WORKDIR /home/workspace

CMD ["/bin/bash"]
''')
    
    dockerfile_arm64 = os.path.join(ops_dir, 'docker', 'Dockerfile.arm64')
    with open(dockerfile_arm64, 'w') as f:
        f.write('''FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

# Install base dependencies
RUN apt-get update && apt-get install -y \\
    build-essential \\
    cmake \\
    pkg-config \\
    git \\
    ruby-dev \\
    curl \\
    jq \\
    && gem install fpm

# Add a non-root user
RUN useradd -ms /bin/bash developer
USER developer
WORKDIR /home/workspace

CMD ["/bin/bash"]
''')
    
    # Create manifest.json if it doesn't exist
    manifest_path = os.path.join(app_dir, 'manifest.json')
    if not os.path.exists(manifest_path):
        manifest = {
            "name": app_name,
            "device_configuration": {
                "nodes": [
                    {
                        "type": "kApplicationNode",
                        "id": 2,
                        "application": {
                            "name": app_name
                        }
                    }
                ]
            }
        }
        
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        print(f"Created basic manifest.json for {app_name}")

def main():
    parser = argparse.ArgumentParser(description="Setup a new Synapse application structure")
    parser.add_argument("app_name", help="Name of the application")
    parser.add_argument("--app_dir", default=os.getcwd(), help="Directory to create the application in (default: current dir)")
    
    args = parser.parse_args()
    
    setup_app_structure(args.app_dir, args.app_name)
    print(f"Application {args.app_name} setup complete!")

if __name__ == "__main__":
    main() 