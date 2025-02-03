from synapse.utils.discover import discover as _discover

def add_commands(subparsers):
    a = subparsers.add_parser(
        "discover", help="Discover Synapse devices on the network"
    )
    a.set_defaults(func=discover)


def discover(args):
    console = Console()

    with console.status("Discovering Synapse devices...", spinner="bouncingBall", spinner_style="yellow"):
        devices = _discover()

    if not devices:
        console.print(f"[bold red]No Synapse devices found")
        return
    
    device_table = Table(title="Synapse Devices")
    device_table.add_column("Name", justify="left")
    device_table.add_column("Host", justify="right")

    for d in devices:
        device_table.add_row(d.name, d.host)

    console.print(device_table)
