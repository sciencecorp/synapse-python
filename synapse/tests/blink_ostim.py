import time

import cv2
import numpy as np

from synapse.device import Device
from synapse.config import Config
from synapse.nodes.stream_in import StreamIn
from synapse.api.synapse_pb2 import DeviceConfiguration
from google.protobuf.json_format import Parse

addr = "localhost:647"
dev = Device(addr)
with open("synapse/tests/test_input_config.json") as config_json:
    config_proto = Parse(config_json.read(), DeviceConfiguration())
    print("Configuring device with the following configuration:")
    dev_config = Config.from_proto(config_proto)
    dev.configure(dev_config)

input_node: StreamIn = dev_config.get_node(1)

rows = 32
cols = 64

print("Sending START...")
dev.start()

on_frame = [0xFF for _ in range(rows * cols)]
off_frame = [0x00 for _ in range(rows * cols)]

try:
    while True:
        # print(f"\nSending frame {frame_number} to MUX01:")
        # print(f"len: {len(it)}. frame: {it}, type: {type(it[0])}")

        input_node.write(bytes(on_frame))
        time.sleep(0.5)
        input_node.write(bytes(off_frame))
        time.sleep(0.5)

except KeyboardInterrupt:
    print("Stopping")
    dev.stop()
