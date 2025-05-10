from synapse.client.taps import Tap

from rich.console import Console
from rich.pretty import pprint
from rich.table import Table


def add_commands(subparsers):
    tap_parser = subparsers.add_parser("taps", help="Interact with taps on the network")

    tap_subparsers = tap_parser.add_subparsers(title="Tap Commands")

    # Now add the list parser to the tap_subparsers
    list_parser = tap_subparsers.add_parser("list", help="list the taps for a device")
    list_parser.set_defaults(func=list_taps)

    stream_parser = tap_subparsers.add_parser("stream", help="Stream a tap")
    stream_parser.add_argument("tap_name", type=str)
    stream_parser.set_defaults(func=stream_taps)


def list_taps(args):
    tap = Tap(args.uri, args.verbose)

    console = Console()

    taps = tap.list_taps()
    table = Table(title="Available Taps", show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("Message Type", style="green")
    table.add_column("Endpoint", style="green")

    for tap in taps:
        table.add_row(tap.name, tap.message_type, tap.endpoint)

    console.print(table)


def stream_taps(args):
    tap = Tap(args.uri, args.verbose)
    taps = tap.list_taps()

    if args.tap_name not in [tap.name for tap in taps]:
        print(f"Tap {args.tap_name} not found")
        return

    tap.connect(args.tap_name)

    console = Console()
    console.print(f"[bold cyan]Streaming tap:[/] [green]{args.tap_name}[/]")

    for message in tap.stream():
        message_size = len(str(message))
        console.print(f"[bold]Message Size:[/] [cyan]{message_size} bytes[/]")
        pprint(message, expand_all=False)
        console.print("---")
