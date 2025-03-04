from synapse.utils.discover import discover_iter as _discover_iter

import sys

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.spinner import Spinner


class DeviceTable:
    def __init__(self):
        self.devices = []
        self.table = Table(show_lines=True, min_width=80)
        self.table.title = Spinner("dots")
        self.table.add_column("Name", justify="left")
        self.table.add_column("Host", justify="right")

    def add_device(self, device):
        self.devices.append(device)
        self.table.add_row(device.name, device.host)


def generate_layout(device_table):
    device_count = len(device_table.devices)
    platform_info = "⌘C to stop" if sys.platform == "darwin" else "Ctrl-C to stop"
    spinner_text = (
        f"Discovering Synapse devices... Found {device_count} so far ({platform_info})"
    )
    device_table.table.title.text = spinner_text
    return device_table.table


def add_commands(subparsers):
    a = subparsers.add_parser(
        "discover", help="Discover Synapse devices on the network"
    )
    a.set_defaults(func=discover)


def discover(args):
    console = Console()
    device_table = DeviceTable()
    try:
        with Live(generate_layout(device_table), refresh_per_second=4) as live:
            for d in _discover_iter():
                device_table.add_device(d)
                live.update(generate_layout(device_table))

    except KeyboardInterrupt:
        pass

    console = Console()
    if not device_table.devices:
        console.print("[bold red]No Synapse devices found")
        return
