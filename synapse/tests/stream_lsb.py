#!/usr/bin/env python3
import queue
import threading
import time
import logging
import csv
from typing import Optional
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

from synapse import ndtp 


CONFIG_PATH = "test_config.json"
OUTPUT_PATH = "output.csv"
DEVICE_URI = "10.40.60.216"

START_CHANNEL = 0
NUM_CHANNELS = 128

STREAM_DURATION = 10

def load_proto_json(filepath):
    print(f"Loading config from {filepath}")
    with open(filepath, "r") as f:
        data = f.read()
        return Parse(data, DeviceConfiguration())


dev = Device(DEVICE_URI)

parser = ndtp.Depacketizer() 

data_queue = queue.Queue()

def reader(duration, stream_out: StreamOut, stop:threading.Event, verbose: bool): 
    packet_count = 0
    avg_bit_rate = 0
    MBps_sum = 0
    bytes_recvd = 0
    start = time.time()
    seq_num = 0
    dropped = 0

    start_sec = time.time()
    while time.time() - start_sec < duration and not stop.is_set():
        data = stream_out.read()
        if data is not None:
            # parser.parse_bytes(data)
            data_queue.put(data)
            dur = time.time() - start
            packet_count += 1
            MBps = (len(data) / dur) / 1e6
            MBps_sum += MBps
            bytes_recvd += len(data)
            avg_bit_rate = (MBps_sum / packet_count) * 8
            if verbose and packet_count % 100 == 0:
                logging.info(f"Recieved {packet_count} packets, {bytes_recvd*8 / 1e6} Mb, {avg_bit_rate} MB/s avg")

            start = time.time()
    end = time.time()

    dur = end - start_sec
    print(f"Recieved {bytes_recvd*8 / 1e6} Mb in {dur} seconds. Avg bit rate: {bytes_recvd*8 / dur / 1e6} Mb/s")
    dev.stop()
    stop.set()


class BinaryWriter():
    def __init__(self, output_path, queue: queue.Queue):
        self.output_path = output_path
        self.q = queue

    def write_worker(self, stop_event: threading.Event):
        with open(self.output_path, mode='wb') as file:
            while not stop_event.is_set():
                try:
                    data = self.q.get()
                    file.write(data)
                except queue.Empty:
                    continue

class CSVWriter():
    def __init__(self, output_path):
        self.sample_buffers: dict[int, queue.Queue] = {}
        self.output_path = output_path

    def add_channel(self, channel_id: int):
        if channel_id not in self.sample_buffers.keys():
            self.sample_buffers[channel_id] = queue.Queue()
        
    def add_samples(self, channel_id: int, samples: list):
        if channel_id not in self.sample_buffers.keys():
            print(f"Channel {channel_id} not found in CSVWriter")
            return

        for sample in samples:
            self.sample_buffers[channel_id].put(sample)

    def write_worker(self, stop_event: threading.Event):
        with open(self.output_path, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(self.sample_buffers.keys())
                
            while not stop_event.is_set():
                row = []
                for channel_id, buffer in self.sample_buffers.items():
                    try:
                        sample = buffer.get(timeout=0.2)
                        row.append(sample)
                    except queue.Empty:
                        row.append(-1)
                writer.writerow(row) 
                

csv_writer = CSVWriter(OUTPUT_PATH)
# bin_writer = BinaryWriter("output.bin", data_queue)

writer = csv_writer

print("Fetching device info...")
info = dev.info()
if info is None:
    print("Couldnt get device info")
    exit(1)


config = Config.from_proto(load_proto_json(CONFIG_PATH))
stream_out = next(
    (n for n in config.nodes if n.type == NodeType.kStreamOut), None
)

ephys = next(
    (n for n in config.nodes if n.type == NodeType.kElectricalBroadband), None
)
if stream_out is None:
    logging.error("No StreamOut node found in config")
    exit(1)

channels = []
for i in range(START_CHANNEL, START_CHANNEL + NUM_CHANNELS):
    channels.append(Channel(i, 2*i, 2*i+1))
    csv_writer.add_channel(i)

ephys.channels = channels 

print("Configuring device...")
if not dev.configure(config):
    print("Failed to configure device")
    exit(1)

print("Fetching configured device info...")
info = dev.info()
if info is None:
    print("Couldnt get device info")
    exit(1)
    

print("Starting device...")
if not dev.start():
    print("Failed to start device")
    exit(1)
print(" - done.")

stop = threading.Event()

read_thread = threading.Thread(target=reader, args=(STREAM_DURATION, stream_out, stop, True))
write_thread = threading.Thread(target=writer.write_worker, args=(stop,))

read_thread.start()
write_thread.start()

try:
    tot_time = 0
    packets = 0
    while not stop.is_set():
        start = time.time()
        data = data_queue.get()
        parser.parse_bytes(data)

        new_packet: Optional[ndtp.NBS12Packet] = parser.get_packet()
        avg_time = 0
        while new_packet:
            for channel_id, samples in new_packet.as_sample_data().items():
                csv_writer.add_samples(channel_id, samples)
            dur = time.time() - start
            packets += 1
            tot_time += dur
            avg_time = tot_time / packets

            new_packet = parser.get_packet()

        dur = time.time() - start 
        if packets % 100 == 0:
            print(f"Processed {packets} packet in {dur} seconds, avg: {avg_time}, len {len(data)}")



except KeyboardInterrupt:
    stop.set()
    


print(info)
print(" - done.")

print("waiting on read thread...")
read_thread.join()
print("waiting on write thread...")
write_thread.join() 
