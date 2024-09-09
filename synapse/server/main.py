import signal
import struct
import socket
import asyncio
import logging
import argparse
from coolname import generate_slug

logging.basicConfig(level=logging.INFO)

from synapse.server.rpc import serve
from synapse.server.autodiscovery import MulticastDiscoveryProtocol


RPC_PORT = 647

DISCOVERY_PORT = 6470
DISCOVERY_ADDR = "224.0.0.245"

SECURITY_MODE = False
SECURITY_PASSPHRASE = None

SERVER_NAME = generate_slug(3)
DEVICE_SERIAL = "SFI000001"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--hidden",
        help="Don't reply to discovery requests without a passphrase",
        action="store_true",
    )
    parser.add_argument("--passphrase", help="Discovery passphrase")
    parser.add_argument(
        "--rpc-port", help="Port to listen for RPC requests", type=int, default=RPC_PORT
    )
    parser.add_argument(
        "--discovery-port",
        help="Port to listen for discovery requests",
        type=int,
        default=6470,
    )
    parser.add_argument(
        "--discovery-addr",
        help="Multicast address to listen for discovery requests",
        default=DISCOVERY_ADDR,
    )
    parser.add_argument("--name", help="Device name", default=SERVER_NAME)
    parser.add_argument("--serial", help="Device serial number", default=DEVICE_SERIAL)
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    args = parser.parse_args()

    if args.hidden and args.passphrase is None:
        parser.error("--hidden requires --passphrase")

    if args.hidden:
        SECURITY_MODE = True

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("", args.discovery_port))
    group = socket.inet_aton(args.discovery_addr)
    mreq = struct.pack("4sL", group, socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    listen = loop.create_datagram_endpoint(
        lambda: MulticastDiscoveryProtocol(
            args.name, args.serial, SECURITY_MODE, args.passphrase, args.rpc_port
        ),
        sock=sock,
    )
    transport, protocol = loop.run_until_complete(listen)

    async def serve_factory():
        return await serve(args.name, args.serial, args.rpc_port)

    main_task = loop.create_task(serve_factory())
    loop.run_until_complete(main_task)

    signal.signal(signal.SIGINT, main_task.cancel)
    signal.signal(signal.SIGINT, listen.cancel)

    try:
        loop.run_forever()
    finally:
        loop.close()
