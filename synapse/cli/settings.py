import synapse as syn
from synapse.client import settings
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
    set_parser.add_argument("key", help="The key to set")
    set_parser.add_argument("value", help="The value to set")
    set_parser.set_defaults(func=set_setting)


def get_settings(args):
    console = Console()

    try:
        with console.status("Getting settings", spinner="bouncingBall"):
            device = syn.Device(args.uri, args.verbose)
            settings_dict = settings.get_all_settings(device)

        if not settings_dict:
            console.print(
                "[yellow]No settings have been configured (all are at default values)[/yellow]"
            )
            console.print("\n[dim]Available settings:[/dim]")
            available = settings.get_available_settings()
            for name, type_name in available.items():
                console.print(f"  [cyan]{name}[/cyan] ({type_name})")
            return

        # Create and populate the settings table
        settings_table = Table(title="Current Settings", show_lines=True)
        settings_table.add_column("Setting", style="cyan")
        settings_table.add_column("Value", style="green")

        for key, value in settings_dict.items():
            settings_table.add_row(key, str(value))

        console.print(settings_table)

    except Exception as e:
        console.print(f"[bold red]{e}[/bold red]")


def set_setting(args):
    console = Console()

    try:
        with console.status("Setting settings", spinner="bouncingBall"):
            device = syn.Device(args.uri, args.verbose)
            updated_value = settings.set_setting(device, args.key, args.value)

        console.print(
            f"[bold green]Setting updated successfully: {args.key} = {args.value}[/bold green]"
        )
        console.print(f"[dim]Confirmed value: {updated_value}[/dim]")

    except Exception as e:
        console.print(f"[bold red]{e}[/bold red]")
