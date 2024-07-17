import time
import socket
import struct

BROADCAST_PORT = 6470
BROADCAST_ADDR = "224.0.0.245"


def add_commands(subparsers):
    a = subparsers.add_parser(
        "discover", help="Discover Synapse devices on the network"
    )
    a.add_argument(
        "auth_code", type=str, default="0", nargs="?", help="Authentication code"
    )
    a.set_defaults(func=discover)


def discover(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    ttl = struct.pack("b", 3)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    try:
        start_time = time.time()
        print("Announcing...")
        sent = sock.sendto(
            "DISCOVER {}".format(args.auth_code).encode("ascii"),
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
                        print("Invalid ID response from {!r}".format(server))
                        continue
                    command, serial, capability, port, name = data
                    print(
                        "{}:{}   {}   {} ({})".format(
                            server[0], port, capability, name, serial
                        )
                    )
                else:
                    print("Unknown response: {!r}".format(command))
    finally:
        sock.close()
