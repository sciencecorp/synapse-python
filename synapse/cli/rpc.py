from synapse.device import Device
from google.protobuf import text_format

def add_commands(subparsers):
  a = subparsers.add_parser('info', help='Get device information')
  a.add_argument('uri', type=str)
  a.set_defaults(func = info)

  a = subparsers.add_parser('start', help='Start the device')
  a.add_argument('uri', type=str)
  a.set_defaults(func = start)

  a = subparsers.add_parser('stop', help='Stop the device')
  a.add_argument('uri', type=str)
  a.set_defaults(func = stop)

  a = subparsers.add_parser('configure', help='Write a configuration to the device')
  a.add_argument('uri', type=str)
  a.set_defaults(func = configure)

def info(args):
    info = Device(args.uri).info()
    print(text_format.MessageToString(info))
    return True

def start(args):
    return Device(args.uri).start()

def stop(args):
    return Device(args.uri).stop()

def configure(args):
    return Device(args.uri).configure()