from pathlib import Path
from synapse.device import Device
from synapse.api.api.synapse_pb2 import DeviceConfiguration
from google.protobuf import text_format
from google.protobuf.json_format import Parse

def add_commands(subparsers):
    a = subparsers.add_parser("info", help="Get device information")
    a.add_argument("uri", type=str)
    a.set_defaults(func=info)

    a = subparsers.add_parser("start", help="Start the device")
    a.add_argument("uri", type=str)
    a.set_defaults(func=start)

    a = subparsers.add_parser("stop", help="Stop the device")
    a.add_argument("uri", type=str)
    a.set_defaults(func=stop)

    a = subparsers.add_parser("configure", help="Write a configuration to the device")
    a.add_argument("uri", type=str)
    a.add_argument("config_file", type=str)
    a.set_defaults(func=configure)


def info(args):
    info = Device(args.uri).info()
    if info:
        print(text_format.MessageToString(info))


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
        print(config_proto)
        return Device(args.uri).configure(config_proto)
