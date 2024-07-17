import time
import os
import queue
import threading
from synapse.api.api.node_pb2 import NodeType
from synapse.device import Device
from synapse.config import Config
from synapse.nodes.electrical_broadband import ElectricalBroadband
from synapse.nodes.optical_stimulation import OpticalStimulation
from synapse.nodes.stream_in import StreamIn
from synapse.nodes.stream_out import StreamOut

def add_commands(subparsers):
    a = subparsers.add_parser("read", help="Read from a device's StreamOut Node")
    a.add_argument("uri", type=str)
    a.add_argument("node_id", type=int)
    a.add_argument("-m", "--multicast", type=str, help="Multicast group")
    a.add_argument("-o", "--output", type=str, help="Output file")
    a.set_defaults(func=read)

    a = subparsers.add_parser("write", help="Write to a device's StreamIn Node")
    a.add_argument("uri", type=str)
    a.add_argument("node_id", type=int)
    a.add_argument("-i", "--input", type=str, help="Input file")
    a.add_argument("-m", "--multicast", type=str, help="Multicast group")
    a.set_defaults(func=write)


def read(args):
    print("Reading from device's StreamOut Node")
    print(f" - multicast: {args.multicast if args.multicast else '<disabled>'}")

    dev = Device(args.uri)
    config = Config()
    stream_out = StreamOut(bind=64401, multicast_group=args.multicast)
    ephys = ElectricalBroadband()

    config.add_node(stream_out)
    config.add_node(ephys)
    config.connect(ephys, stream_out)
    config.set_device(dev)
    print("Configuring device...")
    if not dev.configure(config.to_proto()):
        print("Failed to configure device")
        return
    print(" - done.")

    print("Fetching device info...")
    info = dev.info()
    if info is None:
        print("Couldnt get device info")
        return
    print(info)

    nodes = info.configuration.nodes
    out_node = [node for node in nodes if node.id == args.node_id and node.type == NodeType.kStreamOut]
    if not len(out_node):
        print(f"Node ID {args.node_id} not found in device's signal chain")
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
            tot_bytes = 0
            count = 0
            st = time.time()
            while True:
                data = stream_out.read()
                if data:
                    q.put(data)
                    tot_bytes += len(data)

        except KeyboardInterrupt:
            et = time.time()
            print("Stopping read...")
            stop.set()
            thread.join()
            pass


    else:
        try:
            while True:
                data = stream_out.read()
                if data is not None:
                    value = int.from_bytes(data, "big")
                    print(value)
        except KeyboardInterrupt:
            pass

    print("Avg Mbps: ", tot_bytes*8 / (et - st) / 1e6)
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

    config = Config()
    stream_in = StreamIn(multicast_group=args.multicast)
    optical = OpticalStimulation()

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