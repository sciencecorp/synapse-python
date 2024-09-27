import dataclasses
import json
import queue
import threading
import time
import traceback
from typing import Optional

from google.protobuf.json_format import Parse

from synapse.api.node_pb2 import NodeType
from synapse.api.status_pb2 import DeviceState
from synapse.api.synapse_pb2 import DeviceConfiguration
from synapse.client import Config, Device, StreamOut


class DataclassJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


def add_commands(subparsers):
    a = subparsers.add_parser("read", help="Read from a device's StreamOut node")
    a.add_argument("uri", type=str, help="IP address of Synapse device")
    a.add_argument("--config", type=str, help="Configuration file",)
    a.add_argument("--duration", type=int, help="Duration to read for in seconds")
    a.add_argument("--node_id", type=int, help="ID of the StreamOut node to read from")
    a.set_defaults(func=read)


def load_config_from_file(path):
    with open(path, "r") as f:
        data = f.read()
        proto = Parse(data, DeviceConfiguration())
        return Config.from_proto(proto)


def read(args):
    print(f"Reading from {args.uri}...")

    if not args.config and not args.node_id:
        print("Either `--config` or `--node_id` must be specified.")
        return

    device = Device(args.uri)
    info = device.info()
    assert info is not None, "Couldn't get device info"
    print(info)

    print(f"\n")

    if args.config:
        print("Configuring device...")
        config = load_config_from_file(args.config)
        stream_out = next((n for n in config.nodes if n.type == NodeType.kStreamOut), None)
        assert stream_out is not None, "No StreamOut node found in config"

        if not device.configure(config):
            raise ValueError("Failed to configure device")

        if info.status.state != DeviceState.kRunning:
            print("Starting device...")
            if not device.start():
                raise ValueError("Failed to start device")

    else:
        node = next((n for n in info.configuration.nodes if n.type == NodeType.kStreamOut and n.id == args.node_id), None)
        if node is None:
            print("No StreamOut node found in device configuration; please configure the device with a StreamOut node.")
            return
        
        stream_out = StreamOut._from_proto(node.stream_out)
        stream_out.id = args.node_id
        stream_out.device = device

    print(f"Streaming data... Ctrl+C to stop")
    q = queue.Queue()
    stop = threading.Event()
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


def read_packets(node: StreamOut, q: queue.Queue, duration: Optional[int] = None):
    packet_count = 0
    seq_number = None
    start = time.time()

    while True:
        header, data = node.read()
        if not data:
            continue

        packet_count += 1
        if seq_number is not None and header.seq_number != seq_number + 1:
            print(f"Seq number out of order: {header.seq_number} != {seq_number + 1}")
        seq_number = header.seq_number

        q.put(data)

        if duration and time.time() - start > duration:
            break

    print(f"Recieved {packet_count} packets in {time.time() - start} seconds")


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
            fd.write(json.dumps(data, cls=DataclassJSONEncoder).encode("utf-8"))
            fd.write(b"\n")

        except Exception as e:
            print(f"Error processing data: {e}")
            traceback.print_exc()
            continue
