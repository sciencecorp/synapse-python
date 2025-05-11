from pathlib import Path
import time
from datetime import datetime
from typing import Optional

import synapse as syn
from synapse.api.synapse_pb2 import DeviceConfiguration
from synapse.api.query_pb2 import QueryRequest, QueryResponse, StreamQueryRequest
from synapse.api.status_pb2 import StatusCode

from google.protobuf import text_format
from google.protobuf.json_format import Parse

from rich.console import Console
from rich.pretty import pprint

from synapse.cli.query import StreamingQueryClient
from synapse.utils.log import log_entry_to_str
from synapse.cli.device_info_display import DeviceInfoDisplay


def add_commands(subparsers):
    a = subparsers.add_parser("info", help="Get device information")
    a.set_defaults(func=info)

    b = subparsers.add_parser("query", help="Execute a query on the device")
    b.add_argument("query_file", type=str)
    b.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    b.add_argument("--stream", "-s", action="store_true", help="Stream the output")

    b.set_defaults(func=query)

    c = subparsers.add_parser("start", help="Start the device or an application")
    c.add_argument(
        "config_file",
        nargs="?",
        default=None,
        help=(
            "Optional path to a device configuration JSON file. If supplied, "
            "the CLI first uploads the configuration, then starts the device. "
            "Running `synapsectl start` with no argument simply starts the "
            "device without re-configuring it."
        ),
    )
    c.set_defaults(func=start)

    d = subparsers.add_parser("stop", help="Stop the device or an application")
    d.add_argument(
        "app_name",
        nargs="?",
        default=None,
        help="Name of the application to stop (systemd service). If omitted, stops the whole device via RPC.",
    )
    d.set_defaults(func=stop)

    e = subparsers.add_parser("configure", help="Write a configuration to the device")
    e.add_argument("config_file", type=str)
    e.set_defaults(func=configure)

    f = subparsers.add_parser("logs", help="Get logs from the device")
    f.add_argument("--output", "-o", type=str, help="Optional file to write logs to")
    f.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress output to stdout",
    )
    f.add_argument(
        "--log-level",
        "-l",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Log level to filter by",
    )
    f.add_argument(
        "--follow",
        "-f",
        action="store_true",
        help="Follow log output",
    )
    f.add_argument(
        "--since",
        "-S",
        type=int,
        help="Get logs from the last N milliseconds",
        metavar="N",
    )
    f.add_argument(
        "--start-time",
        type=str,
        help="Start time in ISO format (e.g., '2024-03-14T15:30:00')",
    )
    f.add_argument(
        "--end-time",
        type=str,
        help="End time in ISO format (e.g., '2024-03-14T15:30:00')",
    )
    f.set_defaults(func=get_logs)


def info(args):
    device = syn.Device(args.uri, args.verbose)
    display = DeviceInfoDisplay()
    display.summary(device)


def query(args):
    def load_query_request(path_to_config):
        try:
            with open(path_to_config, "r") as f:
                data = f.read()
                proto = Parse(data, QueryRequest())
                return proto
        except FileNotFoundError:
            console.print(f"[red]Failed to open {path_to_config}: File not found[/red]")
            return None
        except Exception as e:
            console.print(f"[red]Failed to parse query file: {str(e)}[/red]")
            return None

    console = Console()
    if args.stream:
        client = StreamingQueryClient(args.uri, args.verbose)
        query_proto = load_query_request(args.query_file)
        if not query_proto:
            return False
        try:
            return client.stream_query(StreamQueryRequest(request=query_proto))
        except Exception as e:
            console.print(f"[red]Error streaming query: {str(e)}[/red]")
            return False

    if Path(args.query_file).suffix != ".json":
        console.print("[red]Query file must be a JSON file[/red]")
        return False

    try:
        with open(args.query_file) as query_json:
            query_proto = Parse(query_json.read(), QueryRequest())
            console.print("Running query:")
            console.print(query_proto)

            result: QueryResponse = syn.Device(args.uri, args.verbose).query(
                query_proto
            )
            if result:
                console.print(text_format.MessageToString(result))

                if result.HasField("impedance_response"):
                    measurements = result.impedance_response
                    # Write impedance measurements to a CSV file
                    timestamp = time.strftime("%Y%m%d-%H%M%S")
                    filename = f"impedance_measurements_{timestamp}.csv"
                    try:
                        with open(filename, "w") as f:
                            f.write(
                                "Electrode ID,Magnitude (Ohms),Phase (degrees),Status\n"
                            )
                            for measurement in measurements.measurements:
                                f.write(
                                    f"{measurement.electrode_id},{measurement.magnitude},{measurement.phase},1\n"
                                )
                        console.print(
                            f"[green]Impedance measurements saved to {filename}[/green]"
                        )
                    except IOError as e:
                        console.print(
                            f"[red]Error writing impedance measurements: {str(e)}[/red]"
                        )
    except Exception as e:
        console.print(f"[red]Error executing query: {str(e)}[/red]")
        return False


def start(args):
    """Start the Synapse device (and any application services managed by
    *ApplicationControllerNode*).  If an ``app_name`` is supplied we still just
    issue the standard *Device.start* RPC – the controller node on-device will
    decide which systemd service to launch.
    """

    console = Console()

    config_obj = None  # syn.Config if we are provided a *.json* file
    cfg_path = getattr(args, "config_file", None)

    if cfg_path:
        if Path(cfg_path).suffix != ".json":
            console.print("[bold red]Configuration file must be a JSON file (.json)")
            return

        if not Path(cfg_path).is_file():
            console.print(f"[bold red]Configuration file {cfg_path} does not exist")
            return

        # Load the configuration proto and build Config object
        try:
            with open(cfg_path, "r") as f:
                json_text = f.read()
            cfg_proto = Parse(json_text, DeviceConfiguration())
            config_obj = syn.Config.from_proto(cfg_proto)
        except Exception as e:
            console.print(
                f"[bold red]Failed to parse configuration file[/bold red]: {e}"
            )
            return

    device = syn.Device(args.uri, args.verbose)

    device_name = device.get_name()

    # If we have a configuration, apply it first.
    if config_obj is not None:
        with console.status("Configuring device...", spinner="bouncingBall"):
            cfg_ret = device.configure_with_status(config_obj)
            if cfg_ret is None:
                console.print("[bold red]Internal error configuring device")
                return
            if cfg_ret.code != StatusCode.kOk:
                console.print(
                    f"[bold red]Error configuring device[/bold red]\nResponse from {device_name}:\n{cfg_ret.message}"
                )
                return
        console.print("[green]Device configured")

    with console.status("Starting device...", spinner="bouncingBall"):
        start_ret = device.start_with_status()
        if start_ret is None:
            console.print("[bold red]Internal error starting device")
            return
        if start_ret.code != StatusCode.kOk:
            console.print(
                f"[bold red]Error starting device[/bold red]\nResponse from {device_name}:\n{start_ret.message}"
            )
            return

    console.print("[green]Device started")


def stop(args):
    """Stop the Synapse device and, by extension, any application services
    controlled by ApplicationControllerNode.
    """

    console = Console()

    if getattr(args, "app_name", None):
        console.print(
            f"[yellow]Stopping device; application '{args.app_name}' will be "
            "shut down by the on-device ApplicationController.[/yellow]"
        )

    with console.status("Stopping device...", spinner="bouncingBall"):
        stop_ret = syn.Device(args.uri, args.verbose).stop_with_status()
        if not stop_ret:
            console.print("[bold red]Internal error stopping device")
            return
        if stop_ret.code != StatusCode.kOk:
            console.print(f"[bold red]Error stopping\n{stop_ret.message}")
            return
    console.print("[green]Device stopped")


def configure(args):
    if Path(args.config_file).suffix != ".json":
        print("Configuration file must be a JSON file")
        return False

    with open(args.config_file) as config_json:
        console = Console()
        config_proto = Parse(config_json.read(), DeviceConfiguration())
        console.print("Configuring device with the following configuration:")
        config = syn.Config.from_proto(config_proto)
        console.print(config.to_proto())

        config_ret = syn.Device(args.uri, args.verbose).configure_with_status(config)
        if not config_ret:
            console.print("[bold red]Internal error configuring device")
            return
        if config_ret.code != StatusCode.kOk:
            console.print(f"[bold red]Error configuring\n{config_ret.message}")
            return
        console.print("[green]Device configured")


def get_logs(args):
    def parse_datetime(time_str: Optional[str]) -> Optional[datetime]:
        """Parse an ISO format datetime string."""
        if not time_str:
            return None
        try:
            return datetime.fromisoformat(time_str)
        except ValueError:
            return None

    console = Console()
    output_file = open(args.output, "w") if args.output else None

    try:
        if args.follow:
            with console.status("Tailing logs...", spinner="bouncingBall"):
                device = syn.Device(args.uri, args.verbose)
                for log in device.tail_logs(args.log_level):
                    line = log_entry_to_str(log)
                    if output_file:
                        output_file.write(line + "\n")
                    if not args.quiet:
                        print(line)
            return

        start_time = parse_datetime(args.start_time)
        if args.start_time and not start_time:
            console.print(
                "[bold red]Invalid start time format. Use ISO format (e.g., '2024-03-14T15:30:00')"
            )
            return

        end_time = parse_datetime(args.end_time)
        if args.end_time and not end_time:
            console.print(
                "[bold red]Invalid end time format. Use ISO format (e.g., '2024-03-14T15:30:00')"
            )
            return

        with console.status("Getting logs...", spinner="bouncingBall"):
            res = syn.Device(args.uri, args.verbose).get_logs_with_status(
                log_level=args.log_level,
                since_ms=args.since,
                start_time=start_time,
                end_time=end_time,
            )

            if not res or not res.entries:
                console.print("[yellow]No logs found for the specified criteria")
                return

            for log in res.entries:
                line = log_entry_to_str(log)
                if output_file:
                    output_file.write(line + "\n")
                if not args.quiet:
                    print(line)
    finally:
        if output_file:
            output_file.close()
