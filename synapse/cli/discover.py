import socket
import struct

BROADCAST_PORT = 6470
BROADCAST_ADDR = "224.0.0.245"

def add_commands(subparsers):
  a = subparsers.add_parser('discover', help='Discover Synapse devices on the network')
  a.add_argument('auth_code', type=str, default="0", nargs='?', help='Authentication code')
  a.set_defaults(func = discover)

def discover(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    ttl = struct.pack('b', 3)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    try:
        print("Announcing...")
        sent = sock.sendto(
            "DISCOVER {}".format(args.auth_code).encode("ascii"),
            (BROADCAST_ADDR, BROADCAST_PORT)
        )
        while True:
            try:
                data, server = sock.recvfrom(1024)
            except socket.timeout:
                break
            else:
                command, capability, name = data.decode("ascii").split()
                if command == "ID":
                    print("{}:{}   {}   {}".format(server[0], server[1], capability, name))
                    break
                else:
                    print("Unknown response: {!r}".format(command))
    finally:
        sock.close()

