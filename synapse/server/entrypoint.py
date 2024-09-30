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
from synapse.server.nodes import SERVER_NODE_OBJECT_MAP


ENTRY_DEFAULTS = {
    "iface_ip": None,
    "rpc_port": 647,
    "discovery_port": 6470,
    "discovery_addr": "224.0.0.245",
    "server_name": generate_slug(3),
    "device_serial": "SFI000001",
}


def main(
    node_object_map=SERVER_NODE_OBJECT_MAP, peripherals=[], defaults=ENTRY_DEFAULTS
):
    parser = argparse.ArgumentParser(
        description="Simple Synapse Device Simulator (Development)",
        # formatter_class=argparse.ArgumentDefaultsHelpFormatter
        formatter_class=lambda prog: argparse.HelpFormatter(prog, width=124),
    )
    parser.add_argument(
        "--iface-ip",
        help="IP of the network interface to use for multicast traffic",
        required=True,
    )
    parser.add_argument(
        "--rpc-port",
        help="Port to listen for RPC requests",
        type=int,
        default=defaults["rpc_port"],
    )
    parser.add_argument(
        "--discovery-port",
        help="Port to listen for discovery requests",
        type=int,
        default=defaults["discovery_port"],
    )
    parser.add_argument(
        "--discovery-addr",
        help="Multicast address to listen for discovery requests",
        default=defaults["discovery_addr"],
    )
    parser.add_argument("--name", help="Device name", default=defaults["server_name"])
    parser.add_argument(
        "--serial", help="Device serial number", default=defaults["device_serial"]
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    args = parser.parse_args()
    # verify that network interface is real
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.bind((args.iface_ip, 8000))
        logging.info(f"Binding to {s.getsockname()[0]}...")
    except Exception as e:
        parser.error("Invalid --iface-ip given, could not bind to interface")
    finally:
        s.close()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("", args.discovery_port))
    group = socket.inet_aton(args.discovery_addr)
    mreq = struct.pack("=4sL", group, socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    listen = loop.create_datagram_endpoint(
        lambda: MulticastDiscoveryProtocol(
            args.name, args.serial, args.rpc_port
        ),
        sock=sock,
    )
    transport, protocol = loop.run_until_complete(listen)

    async def serve_factory():
        return await serve(
            args.name,
            args.serial,
            args.rpc_port,
            args.iface_ip,
            node_object_map,
            peripherals,
        )

    main_task = loop.create_task(serve_factory())
    loop.run_until_complete(main_task)

    signal.signal(signal.SIGINT, main_task.cancel)
    signal.signal(signal.SIGINT, listen.cancel)

    try:
        loop.run_forever()
    finally:
        loop.close()
