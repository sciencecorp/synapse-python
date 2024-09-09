import logging
import os
import queue
import struct
import threading
import time

from google.protobuf.json_format import Parse, ParseDict

from synapse.api.api.datatype_pb2 import DataType
from synapse.api.api.node_pb2 import NodeType
from synapse.api.api.synapse_pb2 import DeviceConfiguration
from synapse.channel import Channel
from synapse.config import Config
from synapse.device import Device
from synapse.nodes.electrical_broadband import ElectricalBroadband
from synapse.nodes.optical_stimulation import OpticalStimulation
from synapse.nodes.stream_in import StreamIn
from synapse.nodes.stream_out import StreamOut

NDTP_HEADER_SIZE_BYTES = 18


def add_commands(subparsers):
    a = subparsers.add_parser("read", help="Read from a device's StreamOut node")
    a.add_argument("uri", type=str)
    a.add_argument("node_id", type=int)
    a.add_argument("-c", "--config", type=str, help="Config proto (json)")
    a.add_argument("-m", "--multicast", type=str, help="Multicast group")
    a.add_argument("-o", "--output", type=str, help="Output file")
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
        assert config_proto is not None, "Device has no configuration"

        config = Config.from_proto(config_proto)
        stream_out = config.get_node(args.node_id)
        assert (
            stream_out is not None
        ), f"Node id {args.node_id} not found in device configuration"

    print("Starting device...")
    if not device.start():
        raise ValueError("Failed to start device")

    print(f"Streaming data... press Ctrl+C to stop")
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
            read_worker_(stream_out, q, args.verbose)

        except KeyboardInterrupt:
            pass
        finally:
            print("Stopping read...")
            stop.set()
            thread.join()
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
    if not device.stop():
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


def deserialize_header_ndtp(data):
    return struct.unpack("=ciqchh", data[:NDTP_HEADER_SIZE_BYTES])


def read_worker_(stream_out: StreamOut, q: queue.Queue, verbose: bool):
    packet_count = 0
    avg_bit_rate = 0
    MBps_sum = 0
    bytes_recvd = 0
    start = time.time()
    seq_num = 0
    dropped = 0

    start_sec = time.time()
    while time.time() - start_sec < 10:
        data = stream_out.read()
        if data is not None:
            q.put(data)

            dur = time.time() - start
            packet_count += 1
            MBps = (len(data) / dur) / 1e6
            MBps_sum += MBps
            bytes_recvd += len(data)
            avg_bit_rate = MBps_sum / packet_count
            if verbose and packet_count % 10000 == 0:
                logging.info(
                    f"Recieved {packet_count} packets: inst: {MBps} Mbps, avg: {avg_bit_rate} Mbps, dropped: {dropped}, {bytes_recvd*8 / 1e6} Mb recvd"
                )
                print(len(data))

            magic, data_type, t0, seq_num, ch_count, sample_count = (
                deserialize_header_ndtp(data)
            )

            if data_type == DataType.kBroadband:
                print("Broadband")

            # magic = int.from_bytes(data[0:4], "little")
            # if magic != 0xC0FFEE00:
            #     print(f"Invalid magic: {hex(magic)}")

            # recvd_seq_num = int.from_bytes(data[4:8], "little")
            # if recvd_seq_num != seq_num:
            #     print(f"Packet out of order: {recvd_seq_num} != {seq_num}")
            #     dropped += recvd_seq_num - seq_num
            # seq_num = recvd_seq_num + 1

            start = time.time()
    end = time.time()

    dur = end - start_sec
    print(f"Recieved {bytes_recvd*8 / 1e6} Mb in {dur} seconds")
