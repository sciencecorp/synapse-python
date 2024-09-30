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


# read .avi file frame by frame and send to mux01
# filename is doom_clip_64x32.avi
video_path = "synapse/tests/doom_clip_64x32.avi"
cap = cv2.VideoCapture(video_path)
frame_number = 0
try:
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_number += 1

        if frame_number == cap.get(cv2.CAP_PROP_FRAME_COUNT):
            frame_number = 0
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        # Ensure the frame is grayscale
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        it = frame.flatten().tolist()
        # print(f"\nSending frame {frame_number} to MUX01:")
        # print(f"len: {len(it)}. frame: {it}, type: {type(it[0])}")

        input_node.write(frame)
        time.sleep(0.05)

except KeyboardInterrupt:

    cap.release()

    print("Stopping")
    dev.stop()
