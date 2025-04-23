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


def add_commands(subparsers):
    a = subparsers.add_parser("info", help="Get device information")
    a.set_defaults(func=info)

    b = subparsers.add_parser("query", help="Execute a query on the device")
    b.add_argument("query_file", type=str)
    b.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    b.add_argument("--stream", "-s", action="store_true", help="Stream the output")

    b.set_defaults(func=query)

    c = subparsers.add_parser("start", help="Start the device")
    c.set_defaults(func=start)

    d = subparsers.add_parser("stop", help="Stop the device")
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
    console = Console()
    with console.status("Getting device information...", spinner="bouncingBall"):
        info = syn.Device(args.uri, args.verbose).info()

    if not info:
        console.print(f"[bold red]Failed to get device information from {args.uri}")
        return
    pprint(info)


def query(args):
    def load_query_request(path_to_config):
        try:
            with open(path_to_config, "r") as f:
                data = f.read()
                proto = Parse(data, QueryRequest())
                return proto
        except Exception:
            print(f"Failed to open {path_to_config}")
            return None

    if args.stream:
        client = StreamingQueryClient(args.uri, args.verbose)
        query_proto = load_query_request(args.query_file)
        if not query_proto:
            return False
        return client.stream_query(StreamQueryRequest(request=query_proto))

    if Path(args.query_file).suffix != ".json":
        print("Query file must be a JSON file")
        return False

    with open(args.query_file) as query_json:
        query_proto = Parse(query_json.read(), QueryRequest())
        print("Running query:")
        print(query_proto)

        result: QueryResponse = syn.Device(args.uri, args.verbose).query(query_proto)
        if result:
            print(text_format.MessageToString(result))

            if result.HasField("impedance_response"):
                measurements = result.impedance_response
                # Write impedance measurements to a CSV file
                with open(
                    f"impedance_measurements_{time.strftime('%Y%m%d-%H%M%S')}.csv", "w"
                ) as f:
                    f.write("Electrode ID,Magnitude (Ohms),Phase (degrees),Status\n")
                    for measurement in measurements.measurements:
                        f.write(
                            f"{measurement.electrode_id},{measurement.magnitude},{measurement.phase},1\n"
                        )


def start(args):
    console = Console()
    with console.status("Starting device...", spinner="bouncingBall"):
        stop_ret = syn.Device(args.uri, args.verbose).start_with_status()
        if not stop_ret:
            console.print("[bold red]Internal error starting device")
            return
        if stop_ret.code != StatusCode.kOk:
            console.print(f"[bold red]Error starting\n{stop_ret.message}")
            return
    console.print("[green]Device Started")


def stop(args):
    console = Console()
    with console.status("Stopping device...", spinner="bouncingBall"):
        stop_ret = syn.Device(args.uri, args.verbose).stop_with_status()
        if not stop_ret:
            console.print("[bold red]Internal error stopping device")
            return
        if stop_ret.code != StatusCode.kOk:
            console.print(f"[bold red]Error stopping\n{stop_ret.message}")
            return
    console.print("[green]Device Stopped")


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
        console.print("[green]Device Configured")


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
