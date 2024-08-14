import os
import struct
import queue
import threading
import time
import logging
import csv
from synapse.api.api.datatype_pb2 import DataType
from synapse.api.api.node_pb2 import NodeType
from synapse.api.api.synapse_pb2 import DeviceConfiguration
from synapse.device import Device
from synapse.config import Config
from synapse.nodes.electrical_broadband import ElectricalBroadband
from synapse.nodes.optical_stimulation import OpticalStimulation
from synapse.nodes.stream_in import StreamIn
from synapse.nodes.stream_out import StreamOut
from synapse.channel import Channel
from google.protobuf.json_format import Parse, ParseDict, MessageToJson


def add_commands(subparsers):
    a = subparsers.add_parser("read", help="Read from a device's StreamOut node")
    a.add_argument("uri", type=str)
    a.add_argument("node_id", type=int)
    a.add_argument("-c", "--config", type=str, help="Config proto (json)")
    a.add_argument("-d", "--duration", type=int, help="Duration to read for (s)")
    a.add_argument("-m", "--multicast", type=str, help="Multicast group")
    a.add_argument("-o", "--output", type=str, help="Output file")
    a.add_argument("-v", "--verbose", action="store_true", help="Print verbose information about streaming performance")
    a.add_argument("-s", "--csv", action="store_true", help="Write data to csv file")
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

    #print(info)

    if args.config:
        
        config = Config.from_proto(load_proto_json(args.config))
        stream_out = next(
            (n for n in config.nodes if n.type == NodeType.kStreamOut), None
        )

        ephys = next(
            (n for n in config.nodes if n.type == NodeType.kElectricalBroadband), None
        )
        if stream_out is None:
            logging.error("No StreamOut node found in config")
            return
        channels = []
        #for i in range(64, 64 + 64):
        #    channels.append(Channel(i, 2*i, 2*i+1))
        #ephys.channels = channels 

        print("Configuring device...")
        if not dev.configure(config):
            print("Failed to configure device")
            return

        print(" - done.")

    else:
        config_proto = info.configuration
        print(config_proto)
        if config_proto is None:
            print("Device has no configuration")
            return
        config = Config.from_proto(config_proto)
        config.set_device(dev)

        stream_out = config.get_node(args.node_id)
        if stream_out is None:
            print(f"Node id {args.node_id} not found in device configuration")
            return
        

    print("Fetching configured device info...")
    info = dev.info()
    if info is None:
        print("Couldnt get device info")
        return

    print(info)

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
            if args.csv:
                
                with open(args.output, mode='w', newline='') as file:
                    while not stop.is_set() or not q.empty():
                        data = None
                        try:
                            data = q.get(True, 1)
                        except:
                            continue

                        int_list = parse_bytes_to_16bit_ints(data)
                        writer = csv.writer(file)
                        for i in range(0, len(int_list), 64):
                            writer.writerow(int_list[i:i+64]) 
            else:
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
            read_worker_(args.duration, stream_out, q, args.verbose)

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
    stop_resp = dev.stop()
    if not stop_resp:
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


def read_worker_(duration, stream_out: StreamOut, q: queue.Queue, verbose: bool): 
    packet_count = 0
    avg_bit_rate = 0
    MBps_sum = 0
    bytes_recvd = 0
    start = time.time()
    seq_num = 0
    dropped = 0

    start_sec = time.time()
    while time.time() - start_sec < duration:
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
                logging.info(f"Recieved {packet_count} packets, {bytes_recvd*8 / 1e6} Mb")

            start = time.time()
    end = time.time()

    dur = end - start_sec
    print(f"Recieved {bytes_recvd*8 / 1e6} Mb in {dur} seconds")
    

def parse_bytes_to_16bit_ints(byte_data):
    num_of_ints = len(byte_data) // 2
    format_string = f'<{num_of_ints}H'  # '>' for big-endian, 'H' for 16-bit unsigned int
    int_list = struct.unpack(format_string, byte_data)
    return list(int_list)
