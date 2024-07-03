from synapse.api.api.node_pb2 import NodeType
from synapse.device import Device
from synapse.config import Config
from synapse.nodes.electrical_broadband import ElectricalBroadband
from synapse.nodes.stream_out import StreamOut

def add_commands(subparsers):
    a = subparsers.add_parser("read", help="Read from a device's StreamOut Node")
    a.add_argument("uri", type=str)
    a.add_argument("node_id", type=int)
    a.add_argument("-o", "--out", type=str, help="Output file")
    a.set_defaults(func=read)

    a = subparsers.add_parser("write", help="Write to a device's StreamIn Node")
    a.add_argument("uri", type=str)
    a.add_argument("node_id", type=int)
    a.add_argument("-i", "--in", type=str, help="Input file")
    a.set_defaults(func=write)


def read(args):
    dev = Device(args.uri)

    print("Reading from device...")
    info = dev.info()
    if info is None:
        print("Couldnt get device info")
        return

    print(info)

    nodes = info.configuration.nodes
    out_node = [node for node in nodes if node.id == args.node_id and node.type == NodeType.kStreamOut]
    if not len(out_node):
        print(f"Node ID {args.node_id} not found in device's signal chain")
        return

    config = Config()
    stream_out = StreamOut()
    ephys = ElectricalBroadband()

    config.add_node(stream_out)
    config.add_node(ephys)
    config.connect(ephys, stream_out)

    print("Configuring device...")
 
    if not dev.configure(config):
        print("Failed to configure device")
        return
    print(" - done.")

    print("Starting device...")
    if not dev.start():
        print("Failed to start device")
        return
    print(" - done.")

    print("Streaming data... press Ctrl+C to stop")
    if args.out:
        with open(args.out, "wb") as f:
            try:
                while True:
                    data = stream_out.read()
                    if data is not None:
                        f.write(data)
            except KeyboardInterrupt:
                pass
    else:
        try:
            while True:
                data = stream_out.read()
                if data is not None:
                    print(data)
        except KeyboardInterrupt:
            pass

    print("Stopping device...")
    if not dev.stop():
        print("Failed to stop device")
        return
    print(" - done.")


def write(args):
    pass