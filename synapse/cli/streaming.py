import os
import queue
import threading
from synapse.api.api.datatype_pb2 import DataType
from synapse.api.api.node_pb2 import NodeType
from synapse.api.api.synapse_pb2 import DeviceConfiguration
from synapse.device import Device
from synapse.config import Config
from synapse.nodes.electrical_broadband import ElectricalBroadband
from synapse.nodes.optical_stimulation import OpticalStimulation
from synapse.nodes.stream_in import StreamIn
from synapse.nodes.stream_out import StreamOut
from google.protobuf.json_format import Parse, ParseDict


def add_commands(subparsers):
    a = subparsers.add_parser("read", help="Read from a device's StreamOut node")
    a.add_argument("uri", type=str)
    a.add_argument("node_id", type=int)
    a.add_argument("-c", "--config", type=str, help="Config proto (json)")
    a.add_argument("-m", "--multicast", type=str, help="Multicast group")
    a.add_argument("-o", "--output", type=str, help="Output file")
    a.set_defaults(func=read)

    a = subparsers.add_parser("write", help="Write to a device's StreamIn node")
    a.add_argument("uri", type=str)
    a.add_argument("node_id", type=int)
    a.add_argument("-c", "--config", type=str, help="Config proto (json)")
    a.add_argument("-i", "--input", type=str, help="Input file")
    a.add_argument("-m", "--multicast", type=str, help="Multicast group")
    a.set_defaults(func=write)


def load_proto_json(filepath):
    print(f"Loading config from {filepath}")
    with open(filepath, "r") as f:
        data = f.read()
        return Parse(data, DeviceConfiguration())


def read(args):
    print("Reading from device's StreamOut Node")
    print(f" - multicast: {args.multicast if args.multicast else '<disabled>'}")

    dev = Device(args.uri)

    print("Fetching device info...")
    info = dev.info()
    if info is None:
        print("Couldnt get device info")
        return

    print(info)

    if args.config:
        config = Config.from_proto(load_proto_json(args.config))
        stream_out = next(
            (n for n in config.nodes if n.type == NodeType.kStreamOut), None
        )
        if stream_out is None:
            print(
                f"No StreamOut node found in config",
            )
            return

    else:
        config = Config()
        stream_out = StreamOut(
            data_type=DataType.kBroadband,
            shape=[4],
            multicast_group=args.multicast
        )
        ephys = ElectricalBroadband(
            peripheral_id=0
        )

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

    src = args.output if args.output else "stdout"
    print(f"Streaming data out to {src}... press Ctrl+C to stop")
    if args.output:
        stop = threading.Event()
        q = queue.Queue()

        def write_to_file():
            with open(args.output, "wb") as f:
                while not stop.is_set() or not q.empty():
                    data = None
                    try:
                        data = q.get(True, 1)
                    except:
                        continue

                    f.write(data)

        try:
            thread = threading.Thread(target=write_to_file, args=())
            thread.start()
            while True:
                data = stream_out.read()
                if data:
                    q.put(data)

        except KeyboardInterrupt:
            print("Stopping read...")
            stop.set()
            thread.join()
            pass

    else:
        try:
            while True:
                data = stream_out.read()
                if data:
                    value = int.from_bytes(data, "big")
                    print(value)
        except KeyboardInterrupt:
            pass

    print("Stopping device...")
    if not dev.stop():
        print("Failed to stop device")
        return
    print(" - done.")


def write(args):
    print("Writing to device's StreamIn Node")
    print(f" - multicast: {args.multicast if args.multicast else '<disabled>'}")

    if args.input:
        if not os.path.exists(args.input):
            print(f"Input file {args['in']} not found")
            return

    dev = Device(args.uri)

    print("Fetching device info...")
    info = dev.info()
    if info is None:
        print("Couldnt get device info")
        return

    print(info)

    if args.config:
        config = Config.from_proto(load_proto_json(args.config))
        stream_in = next(
            (n for n in config.nodes if n.type == NodeType.kStreamIn), None
        )
        if stream_in is None:
            print("No StreamIn node found in config")
            return
    else:
        config = Config()
        stream_in = StreamIn(
            data_type=DataType.kImage,
            shape=[1],
        )
        optical = OpticalStimulation(
            peripheral_id=0,
            bit_width=4,
            sample_rate=1000,
            gain=1,
        )

        config.add_node(stream_in)
        config.add_node(optical)
        config.connect(stream_in, optical)

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

    src = args.input if args.input else "stdout"
    print(f"Streaming data in from {src}... press Ctrl+C to stop")
    if args.input:
        with open(args.input, "rb") as f:
            try:
                i = 0
                while True:
                    f.seek(4 * i)
                    data = f.read(4)
                    i += 1
                    if not data:
                        break
                    stream_in.write(data)
            except KeyboardInterrupt:
                pass
    else:
        try:
            i = 0
            while True:
                data = stream_in.write(i.to_bytes(4, "big"))
                i += 1
        except KeyboardInterrupt:
            pass

    print("Stopping device...")
    if not dev.stop():
        print("Failed to stop device")
        return
    print(" - done.")
