from synapse.config import Config
from synapse.device import Device
from google.protobuf import text_format
from synapse.nodes.optical_stimulation import OpticalStimulation
from synapse.nodes.stream_in import StreamIn
import zmq

from synapse.nodes.electrical_broadband import ElectricalBroadband
from synapse.nodes.stream_out import StreamOut


def add_commands(subparsers):
    a = subparsers.add_parser("info", help="Get device information")
    a.add_argument("uri", type=str)
    a.set_defaults(func=info)

    a = subparsers.add_parser("start", help="Start the device")
    a.add_argument("uri", type=str)
    a.set_defaults(func=start)

    a = subparsers.add_parser("stop", help="Stop the device")
    a.add_argument("uri", type=str)
    a.set_defaults(func=stop)

    a = subparsers.add_parser("configure", help="Write a configuration to the device")
    a.add_argument("uri", type=str)
    a.set_defaults(func=configure)

    a = subparsers.add_parser("demo", help="Demo streaming data out of the device")
    a.add_argument("uri", type=str)
    a.set_defaults(func=demo)


def info(args):
    info = Device(args.uri).info()
    if info:
        print(text_format.MessageToString(info))


def start(args):
    return Device(args.uri).start()


def stop(args):
    return Device(args.uri).stop()


def configure(args):
    config = Config()

    node_e_broadband = config.add_node(ElectricalBroadband())
    node_stream_out = config.add_node(StreamOut())

    config.connect(node_e_broadband, node_stream_out)

    return Device(args.uri).configure(config)


def demo(args):
    print("Getting device information...")
    info = Device(args.uri).info()
    if info:
        print(text_format.MessageToString(info))

    device = Device(args.uri)

    print(f"Configuring device for stream out...")
    config = Config()
    node_e_broadband = config.add_node(ElectricalBroadband())
    node_stream_out = config.add_node(StreamOut())
    config.connect(node_e_broadband, node_stream_out)

    ok = device.configure(config)
    if not ok:
        print("Failed to configure device")
        return
    print(" - device configured")

    print("Starting...")
    ok = device.start()
    if not ok:
        print("Failed to start device")
        return
    print(" - device started")

    print("Reading...")
    i = 0
    while i < 10:
        try:
            read = node_stream_out.read();
        except zmq.Again:
            print(" - missed?")
            continue
        value = int.from_bytes(read, byteorder='big')
        print(f" - {value}")
        i += 1
    print(" - done")

    print("Stopping...")
    ok = device.stop()
    if not ok:
        print("Failed to stop device")
        return
    print(" - device stopped")
    
    print(f"Configuring device for stream in...")
    config = Config()
    node_o_stim = config.add_node(OpticalStimulation())
    node_stream_in = config.add_node(StreamIn())
    config.connect(node_stream_in, node_o_stim)

    ok = device.configure(config)
    if not ok:
        print("Failed to configure device")
        return
    print(" - device configured")

    print("Starting...")
    ok = device.start()
    if not ok:
        print("Start failed")
        return
    print(" - device started")

    print("Writing...")
    i = 0
    while i < 10:
        ok = node_stream_in.write(i.to_bytes(4, byteorder='big'))
        i += 1
    print(" - done")

