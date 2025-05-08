import zmq
import socket
import threading
import time
import argparse
import binascii


def listen_zmq(endpoint, topic=""):
    """Listen for ZMQ messages"""
    context = zmq.Context()
    subscriber = context.socket(zmq.SUB)
    subscriber.connect(endpoint)

    # Set subscription filter (empty = all messages)
    subscriber.setsockopt_string(zmq.SUBSCRIBE, topic)

    print(f"ZMQ Subscriber connected to {endpoint} with topic '{topic or 'ALL'}'")

    while True:
        try:
            # If multi-part message with topic
            if topic:
                # Get the topic first
                topic_msg = subscriber.recv()
                # Then get the data
                message = subscriber.recv()
            else:
                # Single message
                message = subscriber.recv()

            print(f"Got ZMQ data: {len(message)} bytes")
            # Print first 20 bytes as hex for debugging
            print(f"  Data preview: {binascii.hexlify(message[:20]).decode()}")
        except Exception as e:
            print(f"ZMQ Error: {e}")
            time.sleep(1)


def listen_udp(ip, port):
    """Listen for UDP messages"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ip, port))

    print(f"UDP Listener bound to {ip}:{port}")

    while True:
        try:
            data, addr = sock.recvfrom(8192)  # Buffer size is 8KB
            print(f"Got UDP data from {addr}: {len(data)} bytes")
            # Print first 20 bytes as hex for debugging
            print(f"  Data preview: {binascii.hexlify(data[:20]).decode()}")
        except Exception as e:
            print(f"UDP Error: {e}")
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Listen to ZMQ and UDP taps")

    # ZMQ options
    parser.add_argument(
        "--port",
        type=str,
        default="tcp://10.40.62.57",
        help="ZMQ endpoint to connect to",
    )

    args = parser.parse_args()

    # Start ZMQ listener thread
    connection = f"tcp://10.40.62.57:{args.port}"
    zmq_topic = ""
    zmq_thread = threading.Thread(
        target=listen_zmq, args=(connection, zmq_topic), daemon=True
    )
    zmq_thread.start()

    # Keep main thread alive
    try:
        print("Listening for messages (press Ctrl+C to exit)...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")


if __name__ == "__main__":
    main()
