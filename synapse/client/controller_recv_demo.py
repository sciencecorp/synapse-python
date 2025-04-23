#!/usr/bin/env python3
import zmq
from google.protobuf.json_format import MessageToJson
import time

from synapse.api.datatype_pb2 import Tensor


def main():
    # Create ZMQ context and subscriber socket
    context = zmq.Context()
    subscriber = context.socket(zmq.SUB)

    # Connect to the publisher
    server_ip = "10.40.62.101"
    endpoint = f"tcp://{server_ip}:54878"
    subscriber.connect(endpoint)

    # Subscribe to the topic
    topic = "controller/output"
    subscriber.setsockopt_string(zmq.SUBSCRIBE, topic)

    print(f"Connected to {endpoint}")
    print(f"Subscribed to topic: {topic}")

    try:
        while True:
            # Receive topic
            print("Waiting")
            topic_message = subscriber.recv()
            print(topic_message)
            # Receive tensor data (protobuf serialized)
            tensor_data = subscriber.recv()

            # Parse the tensor data
            tensor = Tensor()
            tensor.ParseFromString(tensor_data)

            # Extract joystick values
            if len(tensor.values) >= 2:
                joystick_x = tensor.values[0]
                joystick_y = tensor.values[1]

                timestamp_ns = tensor.timestamp_ns
                timestamp_s = timestamp_ns / 1e9  # Convert to seconds

                print(f"Received at {time.time():.6f}, message time: {timestamp_s:.6f}")
                print(f"Joystick X: {joystick_x:.4f}, Y: {joystick_y:.4f}")
            else:
                print("Received tensor with unexpected format")
                print(MessageToJson(tensor))

    except KeyboardInterrupt:
        print("Subscriber stopped by user")
    finally:
        # Clean up
        subscriber.close()
        context.term()
        print("Subscriber closed")


if __name__ == "__main__":
    main()
