def add_commands(subparsers):
  a = subparsers.add_parser('list-dev', help='List Synapse devices plugged in via USB')
  a.add_argument('path', type=str)
  a.set_defaults(func = list_devices)

  a = subparsers.add_parser('wifi-config', help='Configure a USB connected Synapse device to connect to a WiFi network')
  a.add_argument('uri', type=str)
  a.set_defaults(func = wifi_config)

def list_devices(args):
    pass

def wifi_config(args):
    pass
