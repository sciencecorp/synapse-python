import time
import socket
import struct

BROADCAST_PORT = 6470
BROADCAST_ADDR = "224.0.0.245"

def discover(auth_code):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
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
                print(f"got: {data}")
                if data[0] == "ID":
                    if len(data) != 5:
                        continue
                    _, serial, capability, port, name = data
                    print(
                        "{}:{}   {}   {} ({})".format(
                            server[0], port, capability, name, serial
                        )
                    )
    finally:
        sock.close()
