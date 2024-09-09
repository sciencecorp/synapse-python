from synapse.utils.discover import discover as _discover

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
    devices = _discover(args.auth_code)
    for d in devices:
      print(f"{d.host}:{d.port}   {d.capability}   {d.name} ({d.serial})")
