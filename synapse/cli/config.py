import argparse
import json

from google.protobuf.json_format import Parse
from rich.console import Console

from synapse import Device
from synapse.api.device_pb2 import DeviceConfiguration
from synapse.client.config import Config
from synapse.cli.files import find_password

SCIFI_DEFAULT_SFTP_USER = "scifi-sftp"


def add_user_arguments(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--username",
        type=str,
        default=SCIFI_DEFAULT_SFTP_USER,
        help="Username for SSH/SFTP connection (default: scifi-sftp)",
    )
    parser.add_argument(
        "--env-file",
        "-e",
        type=str,
        default=".scienv",
        help="Path to environment file containing passwords",
    )
    parser.add_argument(
        "--key-file",
        "-k",
        type=str,
        default=None,
        help="Path to SSH private key file (optional)",
    )


def add_commands(subparsers: argparse._SubParsersAction):
    config_parser = subparsers.add_parser(
        "config", help="Device configuration commands"
    )
    config_subparsers = config_parser.add_subparsers(title="Config Commands")

    # save-default command
    save_parser: argparse.ArgumentParser = config_subparsers.add_parser(
        "save-default",
        help="Save a configuration as the device's default config",
    )
    save_parser.add_argument(
        "config_file",
        type=str,
        help="Path to JSON configuration file to save as default",
    )
    add_user_arguments(save_parser)
    save_parser.set_defaults(func=save_default)

    # clear-default command
    clear_parser: argparse.ArgumentParser = config_subparsers.add_parser(
        "clear-default",
        help="Clear the device's default configuration",
    )
    add_user_arguments(clear_parser)
    clear_parser.set_defaults(func=clear_default)

    # get-default command
    get_parser: argparse.ArgumentParser = config_subparsers.add_parser(
        "get-default",
        help="Display the device's current default configuration",
    )
    get_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output file path (prints to console if not specified)",
    )
    add_user_arguments(get_parser)
    get_parser.set_defaults(func=get_default)


def save_default(args):
    console = Console()

    # Load the config file
    try:
        with open(args.config_file, "r") as f:
            config_json_str = f.read()
    except FileNotFoundError:
        console.print(f"[bold red]Config file not found:[/bold red] {args.config_file}")
        return
    except Exception as e:
        console.print(f"[bold red]Failed to read config file:[/bold red] {e}")
        return

    # Parse JSON to protobuf, then create Config object
    try:
        device_config_proto = Parse(config_json_str, DeviceConfiguration())
        config = Config.from_proto(device_config_proto)
    except Exception as e:
        console.print(f"[bold red]Failed to parse config:[/bold red] {e}")
        return

    # Get password
    device = Device(args.uri, args.verbose)
    dev_name = device.get_name()
    password = find_password(dev_name, args.env_file)
    if password is None and args.key_file is None:
        console.print("[bold red]No password or key file provided[/bold red]")
        return

    # Save the config
    with console.status("Saving default config to device...", spinner="bouncingBall"):
        success = device.save_default_config(
            config,
            username=args.username,
            password=password,
            key_filename=args.key_file,
        )

    if success:
        console.print(
            f"[bold green]Successfully saved default config from {args.config_file}[/bold green]"
        )
    else:
        console.print("[bold red]Failed to save default config[/bold red]")


def clear_default(args):
    console = Console()

    # Get password
    device = Device(args.uri, args.verbose)
    dev_name = device.get_name()
    password = find_password(dev_name, args.env_file)
    if password is None and args.key_file is None:
        console.print("[bold red]No password or key file provided[/bold red]")
        return

    # Clear the config
    with console.status("Clearing default config from device...", spinner="bouncingBall"):
        success = device.clear_default_config(
            username=args.username,
            password=password,
            key_filename=args.key_file,
        )

    if success:
        console.print("[bold green]Successfully cleared default config[/bold green]")
    else:
        console.print("[bold red]Failed to clear default config[/bold red]")


def get_default(args):
    console = Console()

    import synapse.client.sftp as sftp

    # Get password
    device = Device(args.uri, args.verbose)
    dev_name = device.get_name()
    password = find_password(dev_name, args.env_file)
    if password is None and args.key_file is None:
        console.print("[bold red]No password or key file provided[/bold red]")
        return

    hostname = args.uri.split(":")[0]
    remote_path = "/opt/scifi/config/default_config.json"

    with console.status("Fetching default config from device...", spinner="bouncingBall"):
        ssh, sftp_conn = sftp.connect_sftp(
            hostname, args.username, password=password, key_filename=args.key_file
        )
        if ssh is None or sftp_conn is None:
            console.print("[bold red]Failed to connect via SFTP[/bold red]")
            return

        try:
            with sftp_conn.open(remote_path, "r") as f:
                config_content = f.read().decode("utf-8")
        except IOError:
            sftp.close_sftp(ssh, sftp_conn)
            console.print("[yellow]No default config found on device[/yellow]")
            return
        except Exception as e:
            sftp.close_sftp(ssh, sftp_conn)
            console.print(f"[bold red]Failed to read default config:[/bold red] {e}")
            return

        sftp.close_sftp(ssh, sftp_conn)

    # Format the JSON nicely
    try:
        config_json = json.loads(config_content)
        formatted_json = json.dumps(config_json, indent=2)
    except json.JSONDecodeError:
        formatted_json = config_content

    if args.output:
        try:
            with open(args.output, "w") as f:
                f.write(formatted_json)
            console.print(f"[bold green]Default config saved to {args.output}[/bold green]")
        except Exception as e:
            console.print(f"[bold red]Failed to write output file:[/bold red] {e}")
    else:
        console.print("\n[bold blue]Default Configuration:[/bold blue]\n")
        console.print(formatted_json)
