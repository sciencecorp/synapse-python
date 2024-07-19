#!/usr/bin/env python
import argparse
from importlib import metadata
from synapse.cli import discover, rpc, scifi_wifi_config, streaming


def _description():
    return "Synapse Device Manager"


def _epilog():
    return "Synapse Device Manager"


def main():
    parser = argparse.ArgumentParser(
        description=_description(),
        epilog=_epilog(),
        formatter_class=lambda prog: argparse.HelpFormatter(prog, width=124),
    )

    parser.add_argument(
        "--version",
        action="version",
        version="synapsectl %s" % metadata.version("synapse"),
    )
    parser.add_argument(
        "--uri", metavar="-u", type=str, default=None, help="Device control plane URI"
    )

    subparsers = parser.add_subparsers(title="Commands")

    discover.add_commands(subparsers)
    rpc.add_commands(subparsers)
    scifi_wifi_config.add_commands(subparsers)
    streaming.add_commands(subparsers)

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
