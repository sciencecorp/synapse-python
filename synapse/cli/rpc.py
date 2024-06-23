from synapse.device import SynapseDevice

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
    return SynapseDevice(args.uri).info()

def start(args):
    return SynapseDevice(args.uri).start()

def stop(args):
    return SynapseDevice(args.uri).stop()

def configure(args):
    return SynapseDevice(args.uri).configure()