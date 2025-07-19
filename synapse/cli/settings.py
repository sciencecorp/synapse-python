import synapse as syn
from synapse.api.query_pb2 import QueryRequest


from rich.console import Console
from rich.table import Table


def add_commands(subparsers):
    parser = subparsers.add_parser(
        "settings", help="Manage the persistent device settings"
    )

    setting_subparsers = parser.add_subparsers(title="Settings")

    get_parser = setting_subparsers.add_parser(
        "get", help="Get the current settings for a device"
    )
    get_parser.set_defaults(func=get_settings)


def get_settings(args):
    console = Console()

    # Craft a get settings query object
    with console.status("Getting settings", spinner="bouncingBall"):
        request = QueryRequest(
            query_type=QueryRequest.QueryType.kGetSettings, get_settings_query={}
        )
        response = syn.Device(args.uri, args.verbose).query(request)

    if response.status.code != 0:
        console.print(
            f"[bold red] Failed to get settings, why: {response.status.message}[/bold red]"
        )
        return

    settings = response.get_settings_response.settings
    settings_table = Table(title="Settings", show_lines=True)
    settings_table.add_column("Key", style="cyan")
    settings_table.add_column("value", style="green")
    settings_table.add_row("Device Name", settings.name)
    console.print(settings_table)
