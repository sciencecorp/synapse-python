import dataclasses
import json
import logging
import os
import queue
import threading
import time
import traceback

from google.protobuf.json_format import Parse

from synapse.api.datatype_pb2 import DataType
from synapse.api.node_pb2 import NodeType
from synapse.api.synapse_pb2 import DeviceConfiguration
from synapse.client import Config, Device, OpticalStimulation, StreamIn, StreamOut
from synapse.utils import ndtp
from synapse.utils.types import ElectricalBroadbandData


class DataclassJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)

def add_commands(subparsers):
    a = subparsers.add_parser("read", help="Read from a device's StreamOut node")
    a.add_argument("uri", type=str)
    a.add_argument("node_id", type=int)
    a.add_argument("-c", "--config", type=str, help="Config proto (json)")
    a.add_argument("-d", "--duration", type=int, help="Duration to read for (s)")
    a.add_argument("-m", "--multicast", type=str, help="Multicast group")
    a.add_argument("-o", "--output", type=str, help="Output filename (json)")
    a.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print verbose information about streaming performance",
    )
    a.set_defaults(func=read)

    a = subparsers.add_parser("write", help="Write to a device's StreamIn node")
    a.add_argument("uri", type=str)
    a.add_argument("node_id", type=int)
    a.add_argument("-c", "--config", type=str, help="Config proto (json)")
    a.add_argument("-i", "--input", type=str, help="Input file")
    a.add_argument("-m", "--multicast", type=str, help="Multicast group")
    a.set_defaults(func=write)


def load_config_from_file(path):
    with open(path, "r") as f:
        data = f.read()
        proto = Parse(data, DeviceConfiguration())
        return Config.from_proto(proto)

def read(args):
    device = Device(args.uri)
    info = device.info()
    assert info is not None, "Couldn't get device info"

    print("Configuring device...")
    if args.config:
        config = load_config_from_file(args.config)
        stream_out = next(
            (n for n in config.nodes if n.type == NodeType.kStreamOut), None
        )
        assert stream_out is not None, "No StreamOut node found in config"

        if not device.configure(config):
            raise ValueError("Failed to configure device")

    else:
        config_proto = info.configuration
        assert config_proto is not None, "Device has no configuration and none provided"

        config = Config.from_proto(config_proto)
        stream_out = config.get_node(args.node_id)
        assert (
            stream_out is not None
        ), f"Node id {args.node_id} not found in device configuration"

    print("Starting device...")
    if not device.start():
        raise ValueError("Failed to start device")

    print(f"Streaming data... Ctrl+C to stop")

    stop = threading.Event()
    q = queue.Queue()

    try:
        if args.output:
            thread = threading.Thread(
                target=_data_writer, args=(stop, q, args.output, args.verbose)
            )
            thread.start()
        _read_worker(stream_out, q, args.verbose)
    except KeyboardInterrupt:
        pass
    finally:
        print("Stopping read...")
        stop.set()
        thread.join()

    print("Stopping device...")
    if not device.stop():
        print("Failed to stop device")
        return
    print("Stopped")


def _data_writer(stop, q, filename="output", verbose=False):
    filename = f"{filename}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    if filename:
        fd = open(filename, "wb")

    last_seq_num = 0

    while not stop.is_set() or not q.empty():
        data = None
        try:
            data = q.get(True, 1)
            if not data:
                continue

            fd.write(json.dumps(data, cls=DataclassJSONEncoder).encode("utf-8"))
            fd.write(b"\n")

        except Exception as e:
            print(f"Error processing data: {e}")
            traceback.print_exc()
            continue


def _read_worker(stream_out: StreamOut, q: queue.Queue, verbose: bool):
    packet_count = 0
    avg_bit_rate = 0
    MBps_sum = 0
    bytes_recvd = 0
    start = time.time()
    dropped = 0

    start_sec = time.time()
    while time.time() - start_sec < 1 * 60:
        data = stream_out.read()

        if not data:
            continue;
        # forward data to async thread for writing to terminal or disk by
        # adding it to the queue
        q.put(data)

        # generate some benchmarking stats
        dur = time.time() - start
        packet_count += 1
        # MBps = (len(data) / dur) / 1e6
        # MBps_sum += MBps
        # bytes_recvd += len(data)
        # avg_bit_rate = MBps_sum / packet_count
        # if verbose and packet_count % 10000 == 0:
        #     logging.info(
        #         f"Recieved {packet_count} packets: inst: {MBps} Mbps, avg: {avg_bit_rate} Mbps, dropped: {dropped}, {bytes_recvd*8 / 1e6} Mb recvd"
        #     )
        #     print(len(data))
        start = time.time()
    end = time.time()

    dur = end - start_sec
    print(f"Recieved {bytes_recvd*8 / 1e6} Mb in {dur} seconds")


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
        config = load_config_from_file(args.config)
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
