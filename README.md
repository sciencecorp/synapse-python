# Synapse implementation for Python

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

As well as a toy device `synapse-server` for local development, or using as the base for a device implementation:

    % synapse-server --help
    usage: synapse-server [-h] --iface-ip IFACE_IP [--hidden] [--passphrase PASSPHRASE] [--rpc-port RPC_PORT]
                        [--discovery-port DISCOVERY_PORT] [--discovery-addr DISCOVERY_ADDR] [--name NAME] [--serial SERIAL]
                        [-v]

    Simple Synapse Device Simulator (Development)

    options:
    -h, --help            show this help message and exit
    --iface-ip IFACE_IP   IP of the network interface to use for multicast traffic
    --hidden              Don't reply to discovery requests without a passphrase
    --passphrase PASSPHRASE
                            Discovery passphrase
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

    import synapse.client as syn

    dev = syn.Device("127.0.0.1:647")

    print("Device info: ", dev.info())

    recorder = syn.ElectricalBroadband(2, [syn.Channel(0, 1, 2)])
    self.out1 = syn.StreamOut()

    stimulator = syn.OpticalStimulation(syn.ChannelMask(range(0, 1023)))
    self.stim_in = syn.StreamIn()

    config = syn.Config()
    config.add([recorder, self.out1, stimulator, self.stim_in])
    config.connect(recorder, self.out1)
    config.connect(self.stim_in, stimulator)

    dev.start()

## Implementing new Synapse devices

The `synapse.server` package can be used as the base for implementing Synapse-compatible interfaces for non-native systems by simply providing class implementations of the record and/or stimulation nodes (or any other relevant signal chain nodes).

For an example, see the [Blackrock Neurotech CerePlex driver](https://github.com/sciencecorp/synapse-cereplex-driver) implementation.

## Building

To build:

    git submodule update --init
    pip install -r requirements.txt
    make
    python -m build
    pip install dist/synapse-0.1.0-py3-none-any.whl
