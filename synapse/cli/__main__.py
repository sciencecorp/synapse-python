#!/usr/bin/env python
import argparse
import logging
from importlib import metadata
from synapse.cli import discover, rpc, streaming, offline_plot


def main():
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Synapse Device Manager",
        formatter_class=lambda prog: argparse.HelpFormatter(prog, width=124),
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
    parser.add_argument(
        "--uri", metavar="-u", type=str, default=None, help="Device control plane URI"
    )

    subparsers = parser.add_subparsers(title="Commands")

    discover.add_commands(subparsers)
    rpc.add_commands(subparsers)
    streaming.add_commands(subparsers)
    offline_plot.add_commands(subparsers)
    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
