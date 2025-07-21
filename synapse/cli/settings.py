import synapse as syn
from synapse.api.query_pb2 import QueryRequest
from synapse.api.device_pb2 import DeviceSettings, UpdateDeviceSettingsRequest


from rich.console import Console
from rich.table import Table


def add_commands(subparsers):
    parser = subparsers.add_parser(
        "settings", help="Manage the persistent device settings"
    )

    settings_subparsers = parser.add_subparsers(title="Settings")

    get_parser = settings_subparsers.add_parser(
        "get", help="Get the current settings for a device"
    )
    get_parser.set_defaults(func=get_settings)

    set_parser = settings_subparsers.add_parser(
        "set", help="Set a setting key to a value"
    )
    set_parser.set_defaults(func=set_setting)


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


def set_setting(args):
    # console = Console()

    device = syn.Device(args.uri, args.verbose)
    request = UpdateDeviceSettingsRequest(settings=DeviceSettings(name="Wowza"))
    print(request)
    response = device.update_device_settings(request)
    print(response)
