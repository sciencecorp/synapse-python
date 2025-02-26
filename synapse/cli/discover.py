from synapse.utils.discover import discover_iter as _discover_iter

import sys

from rich.console import Console
from rich.table import Table


def add_commands(subparsers):
    a = subparsers.add_parser(
        "discover", help="Discover Synapse devices on the network"
    )
    a.set_defaults(func=discover)


def discover(args):
    console = Console()
    device_table = Table(
        title="Synapse Devices", show_lines=True, row_styles=["dim", ""]
    )
    device_table.add_column("Name", justify="left")
    device_table.add_column("Host", justify="right")

    devices = []
    with console.status(
        "Discovering Synapse devices...", spinner="bouncingBall", spinner_style="yellow"
    ) as status:
        for d in _discover_iter():
            devices.append(d)
            device_table.add_row(d.name, d.host)

            # Clear the previous table and show the updated one
            console.clear()
            console.print(device_table)

            if sys.platform == "darwin":
                status.update(
                    f"Discovering Synapse devices... Found {len(devices)} so far (press ⌘C to stop)"
                )
            else:
                status.update(
                    f"Discovering Synapse devices... Found {len(devices)} so far (press Ctrl-C to stop)"
                )

    if not devices:
        console.print("[bold red]No Synapse devices found")
        return
