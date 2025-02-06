from pathlib import Path
import time
import synapse as syn
from synapse.api.synapse_pb2 import DeviceConfiguration
from synapse.api.query_pb2 import QueryRequest, QueryResponse
from synapse.api.status_pb2 import StatusCode

from google.protobuf import text_format
from google.protobuf.json_format import Parse

from rich.console import Console
from rich.pretty import pprint


def add_commands(subparsers):
    a = subparsers.add_parser("info", help="Get device information")
    a.add_argument("uri", type=str)
    a.set_defaults(func=info)

    b = subparsers.add_parser("query", help="Execute a query on the device")
    b.add_argument("uri", type=str)
    b.add_argument("query_file", type=str)
    b.set_defaults(func=query)

    c = subparsers.add_parser("start", help="Start the device")
    c.add_argument("uri", type=str)
    c.set_defaults(func=start)

    d = subparsers.add_parser("stop", help="Stop the device")
    d.add_argument("uri", type=str)
    d.set_defaults(func=stop)

    e = subparsers.add_parser("configure", help="Write a configuration to the device")
    e.add_argument("uri", type=str)
    e.add_argument("config_file", type=str)
    e.set_defaults(func=configure)


def info(args):
    console = Console()
    with console.status("Getting device information...", spinner="bouncingBall"):
        info = syn.Device(args.uri, args.verbose).info()

    if not info:
        console.print(f"[bold red]Failed to get device information from {args.uri}")
        return
    pprint(info)


def query(args):
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
    return syn.Device(args.uri, args.verbose).start()


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
        config_proto = Parse(config_json.read(), DeviceConfiguration())
        print("Configuring device with the following configuration:")
        config = syn.Config.from_proto(config_proto)
        print(config.to_proto())

        return syn.Device(args.uri, args.verbose).configure(config)
