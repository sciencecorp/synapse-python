#!/usr/bin/env python
import argparse
import logging
from importlib import metadata
from synapse.cli import discover, rpc, streaming, offline_plot, files
from rich.logging import RichHandler
from rich.console import Console
from synapse.utils.discover import discover_iter


def find_device_by_name(name, console):
    """Find a device by name using the discovery process."""
    with console.status(
        f"Searching for device with name {name}...", spinner="bouncingBall"
    ):
        # We are broadcasting data every 1 second
        socket_timeout_sec = 1
        discovery_timeout_sec = 5
        found_devices = []
        devices = discover_iter(socket_timeout_sec, discovery_timeout_sec)
        for device in devices:
            if device.name.lower() == name.lower():
                return f"{device.host}:{device.port}"
            found_devices.append(device)

    console.print(f"[bold red]Device with name {name} not found")
    console.print(
        "[bold red]Either the device is not running or the name is incorrect\n"
    )
    if found_devices:
        console.print("[yellow]We did find some devices:")
        for device in found_devices:
            console.print(f"[yellow]{device.name} ({device.host}:{device.port})")
    return None


def setup_device_uri(args):
    if not args.name and not args.ip:
        return args
    console = Console()
    if args.name:
        args.uri = find_device_by_name(args.name, console)
        if not args.uri:
            return None
    if args.ip:
        args.uri = args.ip
    return args


def main():
    logging.basicConfig(level=logging.INFO, handlers=[RichHandler()])
    parser = argparse.ArgumentParser(
        description="Synapse Device Manager",
        formatter_class=lambda prog: argparse.HelpFormatter(prog, width=124),
    )
    parser.add_argument(
        "--name",
        help="The device name to connect to",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--ip",
        help="The IP address to connect to",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--version",
        action="version",
        version="synapsectl %s" % metadata.version("science-synapse"),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable verbose output",
    )
    subparsers = parser.add_subparsers(title="Commands")
    discover.add_commands(subparsers)
    rpc.add_commands(subparsers)
    streaming.add_commands(subparsers)
    offline_plot.add_commands(subparsers)
    files.add_commands(subparsers)
    args = parser.parse_args()

    # If we need to setup the device URI, do that now
    args = setup_device_uri(args)
    if not args:
        return

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
