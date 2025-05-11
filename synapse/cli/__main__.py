#!/usr/bin/env python
import argparse
import ipaddress
import logging
import sys
from importlib import metadata

from rich.console import Console
from rich.logging import RichHandler

from synapse.cli import (
    build,
    deploy,
    discover,
    files,
    offline_plot,
    rpc,
    streaming,
    taps,
)
from synapse.utils.discover import find_device_by_name


def is_valid_ip(input_str):
    try:
        ipaddress.ip_address(input_str)
        return True
    except ValueError:
        return False


def setup_device_uri(args):
    if not args.uri:
        # User doesn't want to use something that needs a uri
        return args
    if not is_valid_ip(args.uri):
        # User passed in a name
        console = Console()
        device_ip = find_device_by_name(args.uri, console)
        if not device_ip:
            return None
        args.uri = device_ip
    return args


def main():
    logging.basicConfig(level=logging.INFO, handlers=[RichHandler()])
    parser = argparse.ArgumentParser(
        description="Synapse Device Manager",
        formatter_class=lambda prog: argparse.HelpFormatter(prog, width=124),
    )
    parser.add_argument(
        "--uri",
        "-u",
        help="The device identifier to connect to. Can either be the IP address or name",
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
    taps.add_commands(subparsers)
    deploy.add_commands(subparsers)
    build.add_commands(subparsers)
    args = parser.parse_args()

    # If we need to setup the device URI, do that now
    args = setup_device_uri(args)
    if not args:
        return

    try:
        if hasattr(args, "func"):
            args.func(args)
        else:
            parser.print_help()
    except Exception as e:
        console = Console()
        console.log(f"[bold red] Uncaught error during function. Why: {e}")
        parser.print_help()
    except KeyboardInterrupt:
        print("User cancelled request")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Uncaught error in CLI. Why: {e}")
        sys.exit(1)
