from dataclasses import dataclass
import time
import socket

BROADCAST_PORT = 6470
DISCOVERY_TIMEOUT = 2  # Total time we listen for devices


@dataclass
class DeviceInfo:
    host: str
    port: int
    capability: str
    name: str
    serial: str


def discover(timeout_sec=5):
    print(
        f"Starting discovery on UDP port {BROADCAST_PORT}, timeout per recv={timeout_sec}s, total time={DISCOVERY_TIMEOUT}s"
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout_sec)

    # Bind explicitly to 0.0.0.0 so we listen on all interfaces on Windows
    print(f"Binding to ('0.0.0.0', {BROADCAST_PORT})")
    sock.bind(("0.0.0.0", BROADCAST_PORT))

    devices = []
    start_time = time.time()

    try:
        while True:
            # Stop if we've been listening for longer than DISCOVERY_TIMEOUT
            if time.time() - start_time > DISCOVERY_TIMEOUT:
                print("Discovery timeout reached. Stopping.")
                break

            try:
                data, server = sock.recvfrom(1024)
                print(f"Received data from {server}: {data}")
            except socket.timeout:
                print("Socket timed out, waiting for next packet...")
                continue
            except Exception as e:
                print(f"Unexpected error receiving data: {e}")
                continue

            # Try to decode the packet
            try:
                decoded_str = data.decode("ascii", errors="replace").strip()
                print(f"Decoded string: '{decoded_str}'")
            except UnicodeDecodeError:
                print("Received non-ASCII data, skipping.")
                continue

            # Split into tokens and check format
            tokens = decoded_str.split()
            if len(tokens) == 5 and tokens[0] == "ID":
                # Format: "ID <serial> <capability> <port> <name>"
                _, serial, capability, port_str, name = tokens
                try:
                    port_num = int(port_str)
                except ValueError:
                    print(f"Invalid port '{port_str}', skipping.")
                    continue

                dev_info = DeviceInfo(server[0], port_num, capability, name, serial)
                if dev_info not in devices:
                    devices.append(dev_info)
                    print(f"Discovered new device: {dev_info}")
            else:
                print(
                    f"Data doesn't match expected format (ID serial capability port name). Tokens: {tokens}"
                )

    finally:
        print("Closing socket.")
        sock.close()

    print(f"Discovery complete. Found {len(devices)} device(s).")
    return devices
