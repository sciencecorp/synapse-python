from dataclasses import dataclass
import time
import socket
import struct

BROADCAST_PORT = 6470
BROADCAST_ADDR = "224.0.0.245"

@dataclass
class DeviceInfo:
    host: str
    port: int
    capability: str
    name: str
    serial: str


def discover(auth_code, timeout_sec = 3):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout_sec)
    ttl = struct.pack("b", 3)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    devices = []

    try:
        start_time = time.time()

        sent = sock.sendto(
            "DISCOVER {}".format(auth_code).encode("ascii"),
            (BROADCAST_ADDR, BROADCAST_PORT),
        )
        while True:
            if time.time() - start_time > 3:
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
                    devices.append(DeviceInfo(server[0], int(port), capability, name, serial))
    finally:
        sock.close()

    return devices