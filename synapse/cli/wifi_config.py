import getpass


def add_commands(subparsers):
    a = subparsers.add_parser(
        "list-dev", help="List Synapse devices plugged in via USB"
    )
    a.set_defaults(func=list_devices)

    a = subparsers.add_parser(
        "wifi-config",
        help="Configure a USB connected Synapse device to connect to a WiFi network",
    )
    a.add_argument("--ssid", type=str)
    a.add_argument("--security", type=str)
    a.add_argument("--password", type=str)
    a.set_defaults(func=wifi_config)


def list_devices(args):
    pass


def wifi_config(args):
    if args.ssid is None:
        ssid = input("Network SSID: ")
    else:
        ssid = args.ssid

    if args.security is None:
        security_mode = input("Security type [open, wep, wpa, wpa2]: ")
        if security_mode not in ["open", "wep", "wpa", "wpa2"]:
            print("Invalid security type")
            return
    else:
        security_mode = args.security

    if args.password is None:
        password = getpass.getpass("Password: ")
    else:
        password = args.password

    print("Configuring device to connect to network: %s" % ssid)

    # write [ssid, security_mode, password] to device config

    return True
