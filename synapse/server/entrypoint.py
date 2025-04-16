import logging
import signal
import socket
import sys
import asyncio
import argparse
from coolname import generate_slug

from synapse.utils.log import init_logging

from synapse.server.rpc import serve
from synapse.server.autodiscovery import BroadcastDiscoveryProtocol
from synapse.server.nodes import SERVER_NODE_OBJECT_MAP

logging.basicConfig(level=logging.INFO)

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
        help="IP of the network interface to use for streaming data",
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
        help="UDP address to listen for discovery requests",
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

    init_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    # verify that network interface is real
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((args.iface_ip, 8000))
        logging.info(f"Binding to {s.getsockname()[0]}...")
    except Exception:
        parser.error("Invalid --iface-ip given, could not bind to interface")
    finally:
        s.close()

    asyncio.run(async_main(args, node_object_map, peripherals))


async def async_main(args, node_object_map, peripherals):
    logger = logging.getLogger("async_main")
    logger.info("Starting event loop...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: BroadcastDiscoveryProtocol(
            args.discovery_port, args.name, args.serial, args.rpc_port
        ),
        sock=sock,
    )
    logger.info("BroadcastDiscoveryProtocol endpoint created")

    serve_task = asyncio.create_task(
        serve(
            args.name,
            args.serial,
            args.rpc_port,
            args.iface_ip,
            node_object_map,
            peripherals,
        )
    )
    logger.info("serve task created")

    if sys.platform == "win32":
        # Windows-specific signal handling
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            asyncio.create_task(
                shutdown(loop, [serve_task], transport, signal.Signals(signum))
            )

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal_handler)
    else:
        # Unix-like systems can use add_signal_handler
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(
                    shutdown(loop, [serve_task], transport, s)
                ),
            )

    try:
        await serve_task
    except asyncio.CancelledError:
        logger.info("Serve task cancelled")
    finally:
        logger.info("Closing transport")
        transport.close()


async def shutdown(loop, tasks, transport, signal):
    logger = logging.getLogger("shutdown")
    logger.info(f"Received exit signal from {signal.name}, shutting down...")

    for task in tasks:
        task.cancel()

    logger.info("Closing transport")
    transport.close()

    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()
