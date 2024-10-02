# Synapse Python client

This repo contains the Python client for the [Synapse API](https://science.xyz/technologies/synapse). More information about the API can be found in the [docs](https://science.xyz/docs/d/synapse/index).

Includes `synapsectl` command line utility:

    % synapsectl --help
    usage: synapsectl [-h] [--version] [--uri -u]
                    {discover,info,query,start,stop,configure,list-dev,wifi-select,wifi-config,read,write} ...

    Synapse Device Manager

    options:
    -h, --help            show this help message and exit
    --version             show program's version number and exit
    --uri -u              Device control plane URI

    Commands:
    {discover,info,query,start,stop,configure,list-dev,wifi-select,wifi-config,read,write}
        discover            Discover Synapse devices on the network
        info                Get device information
        query               Execute a query on the device
        start               Start the device
        stop                Stop the device
        configure           Write a configuration to the device
        list-dev            List Synapse devices plugged in via USB
        wifi-select         Configure a USB connected Synapse device to use a known WiFi network
        wifi-config         Configure a USB connected Synapse device for a new WiFi network
        read                Read from a device's StreamOut node
        write               Write to a device's StreamIn node

As well as the base for a device implementation (`synapse/server`),

And a toy device `synapse-sim` for local development,

    % synapse-sim --help
    usage: synapse-sim [-h] --iface-ip IFACE_IP [--rpc-port RPC_PORT]
                        [--discovery-port DISCOVERY_PORT] [--discovery-addr DISCOVERY_ADDR] [--name NAME] [--serial SERIAL]
                        [-v]

    Simple Synapse Device Simulator (Development)

    options:
    -h, --help            show this help message and exit
    --iface-ip IFACE_IP   IP of the network interface to use for multicast traffic
    --rpc-port RPC_PORT   Port to listen for RPC requests
    --discovery-port DISCOVERY_PORT
                            Port to listen for discovery requests
    --discovery-addr DISCOVERY_ADDR
                            Multicast address to listen for discovery requests
    --name NAME           Device name
    --serial SERIAL       Device serial number
    -v, --verbose         Enable verbose output

## Writing clients

This library offers an idiomatic Python interpretation of the Synapse API:

```python
import synapse as syn

device = syn.Device("127.0.0.1:647")
info = device.info()

print("Device info: ", device.info())

stream_out = syn.StreamOut(label="my broadband", multicast_group="239.0.0.1")
e_broadband = syn.ElectricalBroadband(
    peripheral_id=2,
    channels=[syn.Channel(id=c, electrode_id=c * 2, reference_id=c * 2 + 1) for c in range(32)],
    sample_rate=30000,
    bit_width=12,
    gain=20.0,
    low_cutoff_hz=500.0,
    high_cutoff_hz=6000.0,
)

config = syn.Config()
config.add_node(stream_out)
config.add_node(e_broadband)
config.connect(e_broadband, stream_out)

device.configure(config)
device.start()

```

## Implementing new Synapse devices

The `synapse.server` package can be used as the base for implementing Synapse-compatible interfaces for non-native systems by simply providing class implementations of the record and/or stimulation nodes (or any other relevant signal chain nodes).

For an example, see the [Blackrock Neurotech CerePlex driver](https://github.com/sciencecorp/synapse-cereplex-driver) implementation.

## Building

Dependencies:

    git submodule update --init
    pip install -r requirements.txt
    make

To build and install in development mode:

    pip install -e .

To build and install a wheel:

    python -m build

    # and optionally install
    pip install dist/synapse-*-py3-none-any.whl
