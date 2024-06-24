# Synapse Python client

Includes `synapsectl` command line utility:

    python -m synapse.cli.main --help

To build:

    git submodule init
    git submodule update
    pip install -r requirements.txt
    make
    python -m build