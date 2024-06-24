#!/usr/bin/env python
import argparse
from synapse.cli import discover, rpc, wifi_config


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
        "--uri", metavar="-u", type=str, default=None, help="Device control plane URI"
    )

    subparsers = parser.add_subparsers(title="Commands")

    discover.add_commands(subparsers)
    rpc.add_commands(subparsers)
    wifi_config.add_commands(subparsers)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
