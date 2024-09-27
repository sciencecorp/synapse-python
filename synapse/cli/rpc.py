from pathlib import Path
from synapse.client import Config, Device
from synapse.api.synapse_pb2 import DeviceConfiguration
from synapse.api.channel_pb2 import Channel
from synapse.api.query_pb2 import QueryRequest, ImpedanceQuery
from google.protobuf import text_format
from google.protobuf.json_format import Parse


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
    info = Device(args.uri).info()
    if info:
        print(text_format.MessageToString(info))


def query(args):
    if Path(args.query_file).suffix != ".json":
        print("Query file must be a JSON file")
        return False

    with open(args.query_file) as query_json:
        query_proto = Parse(query_json.read(), QueryRequest())
        print("Running query:")
        print(query_proto)

        result = Device(args.uri).query(query_proto)
        if result:
            print(text_format.MessageToString(result))


def start(args):
    return Device(args.uri).start()


def stop(args):
    return Device(args.uri).stop()


def configure(args):
    if Path(args.config_file).suffix != ".json":
        print("Configuration file must be a JSON file")
        return False

    with open(args.config_file) as config_json:
        config_proto = Parse(config_json.read(), DeviceConfiguration())
        print("Configuring device with the following configuration:")
        print(config_proto)

        return Device(args.uri).configure(Config.from_proto(config_proto))
