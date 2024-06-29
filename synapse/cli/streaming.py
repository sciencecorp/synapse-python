from synapse.device import Device
from synapse.config import Config
from synapse.nodes.electrical_broadband import ElectricalBroadband
from synapse.nodes.stream_out import StreamOut
from synapse.generated.api.node_pb2 import NodeType

def add_commands(subparsers):
    a = subparsers.add_parser("read", help="Read from a device StreamOut Node")
    a.add_argument("uri", type=str)
    a.add_argument("node_id", type=int)
    a.set_defaults(func=read)

    a = subparsers.add_parser("write", help="Write to a device StreamIn Node")
    a.add_argument("uri", type=str)
    a.add_argument("node_id", type=int)
    a.set_defaults(func=write)


def read(args):

    config = Config()
    stream_out = StreamOut()
    ephys = ElectricalBroadband()
    config.add_node(stream_out)
    config.add_node(ephys)
    config.connect(ephys, stream_out)

    dev = Device(args.uri)
    st = dev.configure(config)
    if not st:
        print("Failed to configure device")
        return

    info = dev.info()
    if info is None:
        print("Couldnt get device info")
        return
    print(info)
    nodes = info.configuration.nodes
    out_node = None
    for node in nodes:
        if (node.id == args.node_id):
            if node.type != NodeType.kStreamOut:
                print(f"Node ID {args.node_id} is not a StreamOut node")
                return
            out_node = node
            break

    if out_node is None:
        print(f"Node ID {args.node_id} not found in device's signal chain")
        return

    from io import BytesIO
    if not dev.start():
        print("Failed to start device")
        return
    with open("test.txt", "wb") as f:
        for i in range(250):
            data = stream_out.read()
            # wb = BytesIO(data[0])
            # for d in data:

                # print(type(d))
            f.writelines(data)

    print("Stopping device")
    dev.stop()

def write(args):
    pass