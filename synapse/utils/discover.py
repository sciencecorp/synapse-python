from dataclasses import dataclass
import time
import socket

BROADCAST_PORT = 6470
DISCOVERY_TIMEOUT = 2

@dataclass
class DeviceInfo:
    host: str
    port: int
    capability: str
    name: str
    serial: str

def discover(timeout_sec = 0.2):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout_sec)
    sock.bind(("", BROADCAST_PORT))

    devices = []
    try:
        start_time = time.time()

        while True:
            now = time.time()
            if now - start_time > DISCOVERY_TIMEOUT:
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
                    dev_info = DeviceInfo(server[0], int(port), capability, name, serial)
                    if dev_info not in devices:
                        devices.append(dev_info)
    finally:
        sock.close()

    return devices