from dataclasses import dataclass
import time
import socket
import sys


BROADCAST_PORT = 6470
DISCOVERY_TIMEOUT_SEC = 10

@dataclass
class DeviceInfo:
    host: str
    port: int
    capability: str
    name: str
    serial: str

def discover_iter(socket_timeout_sec=1, discovery_timeout_sec=DISCOVERY_TIMEOUT_SEC):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if sys.platform != 'win32':
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.settimeout(socket_timeout_sec)
    sock.bind(("", BROADCAST_PORT))

    devices = []  # Keep track of what we've seen to avoid duplicates
    try:
        start_time = time.time()

        while True:
            now = time.time()
            if now - start_time > discovery_timeout_sec:
                break
            try:
                data, server = sock.recvfrom(1024)
            except socket.timeout:
                continue
            else:
                data = data.decode("ascii").split()
                if data[0] == "ID":
                    if len(data) != 5:
                        continue
                    _, serial, capability, port, name = data
                    dev_info = DeviceInfo(
                        server[0], int(port), capability, name, serial
                    )
                    if dev_info not in devices:
                        devices.append(dev_info)
                        yield dev_info
    finally:
        sock.close()


def discover(timeout_sec=DISCOVERY_TIMEOUT_SEC):
    return list(discover_iter(timeout_sec))
