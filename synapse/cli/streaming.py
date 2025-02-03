import json
import queue
import threading
import time
import traceback
from typing import Optional
from operator import itemgetter

from google.protobuf.json_format import Parse

from synapse.api.node_pb2 import NodeType
from synapse.api.status_pb2 import DeviceState
from synapse.api.synapse_pb2 import DeviceConfiguration
import synapse as syn
import synapse.client.channel as channel
import synapse.utils.ndtp_types as ndtp_types


from rich.console import Console
from rich.pretty import pprint

def add_commands(subparsers):
    a = subparsers.add_parser("read", help="Read from a device's StreamOut node")
    a.add_argument("uri", type=str, help="IP address of Synapse device")
    a.add_argument(
        "--config",
        type=str,
        help="Configuration file",
    )
    a.add_argument("--num_ch", type=int, help="Number of channels to read from, overrides config")
    a.add_argument("--bin", type=bool, help="Output binary format instead of JSON")
    a.add_argument("--duration", type=int, help="Duration to read for in seconds")
    a.add_argument("--node_id", type=int, help="ID of the StreamOut node to read from")
    a.add_argument("--ignore-buffers", action="store_true", default=False,help="Ignore misconfigured UDP buffers")
    a.set_defaults(func=read)


def load_config_from_file(path):
    with open(path, "r") as f:
        data = f.read()
        proto = Parse(data, DeviceConfiguration())
        return syn.Config.from_proto(proto)


def read(args):
    console = Console()
    
    print(f"Reading from {args.uri}...")

    if not args.config and not args.node_id:
        print("Either `--config` or `--node_id` must be specified.")
        return

    device = syn.Device(args.uri)
    info = device.info()
    assert info is not None, "Couldn't get device info"
    print(info)

    print(f"\n")

    if args.config:
        print("Configuring device...")
        config = load_config_from_file(args.config)
        stream_out = next(
            (n for n in config.nodes if n.type == NodeType.kStreamOut), None
        )
        assert stream_out is not None, "No StreamOut node found in config"
        ephys = next(
            (n for n in config.nodes if n.type == NodeType.kElectricalBroadband), None
        )
        num_ch = len(ephys.channels)
        if args.num_ch:
            num_ch = args.num_ch
            offset = 0
            channels = []
            for ch in range(offset, offset + num_ch):
                channels.append(channel.Channel(ch, 2*ch, 2*ch + 1))
        
            ephys.channels = channels

        if not device.configure(config):
            raise ValueError("Failed to configure device")

        if info.status.state != DeviceState.kRunning:
            print("Starting device...")
            if not device.start():
                raise ValueError("Failed to start device")

    else:
        node = next(
            (
                n
                for n in info.configuration.nodes
                if n.type == NodeType.kStreamOut and n.id == args.node_id
            ),
            None,
        )
        if node is None:
            print(
                "No StreamOut node found in device configuration; please configure the device with a StreamOut node."
            )
            return

        stream_out = syn.StreamOut._from_proto(node.stream_out)
        stream_out.id = args.node_id
        stream_out.device = device

    print(f"Streaming data... Ctrl+C to stop")
    q = queue.Queue()
    stop = threading.Event()
    if args.bin:
        thread = threading.Thread(target=_binary_writer, args=(stop, q, num_ch))
    else:
        thread = threading.Thread(target=_data_writer, args=(stop, q))
    thread.start()

    try:
        read_packets(stream_out, q, args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        print("Stopping read...")
        stop.set()
        thread.join()

    if args.config:
        print("Stopping device...")
        if not device.stop():
            print("Failed to stop device")
            return
        print("Stopped")


def read_packets(node: syn.StreamOut, q: queue.Queue, duration: Optional[int] = None):
    packet_count = 0
    seq_number = None
    dropped_packets = 0
    start = time.time()
    print_interval = 1000
    print(f"Reading packets for duration {duration} seconds" if duration else "Reading packets...")
    while True:
        header, data = node.read()
        if not data:
            continue

        packet_count += 1
        if seq_number is None:
            seq_number = header.seq_number
        else:
            expected = seq_number + 1
            if expected == 2**16:
                expected = 0
            if header.seq_number != expected:
                print(f"Seq number out of order: {header.seq_number} != {expected}")
                dropped_packets += header.seq_number - (expected)
            seq_number = header.seq_number

        q.put(data)
        if packet_count == 1:
            print(f"First packet received at {time.time() - start} seconds")
        if packet_count % print_interval == 0:
            print(f"Recieved {packet_count} packets in {time.time() - start} seconds. Dropped {dropped_packets} packets ({(dropped_packets / packet_count) * 100}%)")
        if duration and (time.time() - start) > duration:
            break

    print(f"Recieved {packet_count} packets in {time.time() - start} seconds. Dropped {dropped_packets} packets ({(dropped_packets / packet_count) * 100}%)")


def _binary_writer(stop, q, num_ch):
    filename = f"synapse_data_{time.strftime('%Y%m%d-%H%M%S')}.dat"

    print(f"Writing binary data from {num_ch} channels to {filename}")
    if filename:
        fd = open(filename, "wb")
    
    channel_data = []
    while not stop.is_set() or not q.empty():
        try:
            data: ndtp_types.ElectricalBroadbandData = q.get(True, 1)
        except queue.Empty:
            continue

        try:
            for ch_id, samples in data.samples:
                channel_data.append([ch_id, samples])
                if len(channel_data) == num_ch:
                    channel_data.sort(key=itemgetter(0))
                    channel_samples = [ch_data[1] for ch_data in channel_data]
                    frames = list(zip(*channel_samples))
                    channel_data = []

                    for frame in frames:
                        for sample in frame:
                            fd.write(int(sample).to_bytes(2, byteorder="little", signed=False))

        except Exception as e:
            print(f"Error processing data: {e}")
            traceback.print_exc()
            continue
                

def _data_writer(stop, q):
    filename = f"synapse_data_{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    if filename:
        fd = open(filename, "wb")

    while not stop.is_set() or not q.empty():
        try:
            data = q.get(True, 1)
        except queue.Empty:
            continue

        try:
            fd.write(json.dumps(data.to_list()).encode("utf-8"))
            fd.write(b"\n")

        except Exception as e:
            print(f"Error processing data: {e}")
            traceback.print_exc()
            continue
