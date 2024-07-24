import os
import re
import getpass
import serial
from time import sleep

if os.name == "nt":
    from serial.tools.list_ports_windows import comports
elif os.name == "posix":
    from serial.tools.list_ports_posix import comports

SCIFI_USB_VENDOR_ID = 0x0403
SCIFI_USB_PRODUCT_ID = 0x6015

DEFAULT_HEADSTAGE_USER = "root"
DEFAULT_HEADSTAGE_PASSWORD = "oelinux123"


def add_commands(subparsers):
    a = subparsers.add_parser(
        "list-dev", help="List Synapse devices plugged in via USB"
    )
    a.set_defaults(func=list_devices)
    a.add_argument("--vendor-id", type=str, default=SCIFI_USB_VENDOR_ID)
    a.add_argument("--product-id", type=str, default=SCIFI_USB_PRODUCT_ID)

    b = subparsers.add_parser(
        "wifi-select",
        help="Configure a USB connected Synapse device to use a known WiFi network",
    )
    b.add_argument("device_path", type=str)
    b.add_argument("--ssid", type=str)
    b.add_argument("--headstage-user", type=str, default=DEFAULT_HEADSTAGE_USER)
    b.add_argument("--headstage-password", type=str, default=DEFAULT_HEADSTAGE_PASSWORD)
    b.add_argument("--vendor-id", type=str, default=SCIFI_USB_VENDOR_ID)
    b.add_argument("--product-id", type=str, default=SCIFI_USB_PRODUCT_ID)
    b.set_defaults(func=wifi_select)

    c = subparsers.add_parser(
        "wifi-config",
        help="Configure a USB connected Synapse device for a new WiFi network",
    )
    c.add_argument("device_path", type=str)
    c.add_argument("--ssid", type=str)
    c.add_argument("--security", type=str)
    c.add_argument("--password", type=str)
    c.add_argument("--headstage-user", type=str, default=DEFAULT_HEADSTAGE_USER)
    c.add_argument("--headstage-password", type=str, default=DEFAULT_HEADSTAGE_PASSWORD)
    c.add_argument("--vendor-id", type=str, default=SCIFI_USB_VENDOR_ID)
    c.add_argument("--product-id", type=str, default=SCIFI_USB_PRODUCT_ID)

    c.set_defaults(func=wifi_config)


def _list_devices(args):
    iterator = comports(include_links=False)
    ports = [
        port.device
        for port in iterator
        if port.vid == args.vendor_id and port.pid == args.product_id
    ]
    return ports


def list_devices(args):
    ports = _list_devices(args)
    if len(ports) == 0:
        print("No Synapse devices found")
    else:
        print("Found Synapse devices:")
        for port in ports:
            print(port)


def wifi_select(args):
    ports = _list_devices(args)
    if args.device_path not in ports:
        print("Device %s not found or invalid" % args.device_path)
        return

    if args.ssid is None:
        ssid = input("Network SSID: ")
    else:
        ssid = args.ssid

    console = serial.Serial(ports[0], 115200, timeout=1)

    if not _attempt_login(console, args.headstage_user, args.headstage_password):
        print("Couldn't access headstage, fix the state and retry")
        return

    if not _check_valid_command_line(console):
        print("Failed to validate command line, something is bad, fix state and retry")
        return

    network_id = _check_if_wpa_network_exists(console, ssid)

    if network_id is False:
        print("Network %s not found" % ssid)
        _logout(console)
        return

    if not _enable_wpa_network(console, network_id):
        print("Failed to enable network")
    else:
        print("Connected to network %s" % ssid)

    _logout(console)


def wifi_config(args):
    ports = _list_devices(args)
    if args.device_path not in ports:
        print("Device %s not found or invalid" % args.device_path)
        return

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

    console = serial.Serial(ports[0], 115200, timeout=1)

    _program_wpa_supplicant(
        console, args.headstage_user, args.headstage_password, ssid, password
    )

    return True


def _program_wpa_supplicant(console, headstage_user, headstage_pass, ssid, password):
    if not _attempt_login(console, headstage_user, headstage_pass):
        print("Couldn't access headstage, fix the state and retry")
        # # if not good for login, try to force reset
        # if not _force_reset(console):
        #     print("Failed to force reset, try rebooting headstage")
        #     return
        # print("Forced reset, trying to login again")
        # if not _attempt_login(console, headstage_user, headstage_pass):
        #     print("Failed to login after reset")
        #     return

    if not _check_valid_command_line(console):
        print("Failed to validate command line, something is bad, fix state and retry")
        return

    network_id = _check_if_wpa_network_exists(console, ssid)

    if network_id is False:
        if not _add_wpa_network(console, ssid, password):
            _logout(console)
            return

        network_id = _check_if_wpa_network_exists(console, ssid)
        if network_id is False:
            _logout(console)
            return
        else:
            print("Added network %s with id %s" % (ssid, network_id))
    else:
        print("Found network %s with id %s" % (ssid, network_id))

    if not _set_wpa_network_ssid(console, network_id, ssid):
        _logout(console)
        return
    else:
        print("Set network %s ssid to %s" % (ssid, network_id))

    if not _set_wpa_network_password(console, network_id, password):
        _logout(console)
        return
    else:
        print("Set network %s password" % ssid)

    if not _enable_wpa_network(console, network_id):
        _logout(console)
        return

    # check if connected
    # if connected, return success

    if not _logout(console):
        print("Failed to logout")
        return


def _attempt_login(console, username, password):
    console.write(b"\r\n")
    sleep(0.1)
    data = console.read(1024)
    cmp = re.compile(b"login\: $").search(data)
    if cmp is None:
        return False

    console.write(username.encode())
    sleep(0.1)
    console.write(b"\r")

    data = console.read(1024)
    cmp = re.compile(b"Password\: $").search(data)

    if cmp is None:
        return False

    console.write(password.encode())
    sleep(0.1)
    console.write(b"\r")
    sleep(1)

    data = console.read(1024)
    cmp = re.compile(b"\\r\\nroot@[a-zA-Z0-9.-]+:~# ").search(data)
    if cmp is None:
        return False

    return True


def _logout(console):
    console.write(b"logout")
    sleep(0.1)
    console.write(b"\r")
    sleep(7)
    data = console.read(1024)
    cmp = re.compile(b"login\: $").search(data)
    if cmp is None:
        return False
    return True


def _check_valid_command_line(console):
    console.write(b"\r\n")
    sleep(0.1)
    data = console.read(1024)
    cmp = re.compile(b"\\r\\nroot@[a-zA-Z0-9.-]+:~# ").search(data)
    if cmp is None:
        return False
    return True


def _force_reset(console):
    console.write(b"\r")
    sleep(0.1)
    console.write(b"\x04")
    sleep(0.1)
    console.write(b"\r")
    sleep(0.1)

    data = console.read(1024)
    cmp = re.compile(b"login\: $").search(data)
    if cmp is None:
        return False
    return True


def _list_wpa_networks(console):
    console.write(b"wpa_cli list_networks")
    sleep(0.1)
    console.write(b"\r")
    sleep(0.1)
    data = console.read(1024)
    cmp = re.compile(b"\\r\\nSelected interface").search(data)
    if cmp is None:
        return False
    return data


def _check_if_wpa_network_exists(console, ssid):
    networks = _list_wpa_networks(console)
    if networks is False:
        return False
    cmp = re.compile(b"\\r\\n[0-9]+\\t" + ssid.encode() + b"\\t").search(networks)
    if cmp is None:
        return False
    return cmp.group(0).split(b"\t")[0].decode().strip()


def _add_wpa_network(console):
    console.write(b"wpa_cli add_network")
    sleep(0.1)
    console.write(b"\r")
    sleep(0.1)

    data = console.read(1024)
    cmp = re.compile(b"\\r\\nSelected interface").search(data)
    if cmp is None:
        print("Failed to add network")
        return False

    network_id = cmp.group(0).split(b"\t")[0].decode().strip()
    print("Added network, id: %s" % network_id)

    return network_id


def _set_wpa_network_ssid(console, network_id, ssid):
    console.write(
        ("wpa_cli set_network %s ssid '\"%s\"'" % (network_id, ssid)).encode()
    )
    sleep(0.1)
    console.write(b"\r")
    sleep(0.1)
    data = console.read(1024)
    cmp = re.compile(b"\\r\\nOK").search(data)
    if cmp is None:
        print("Failed to set network %s ssid as %s" % (network_id, ssid))
        return False

    print("Set network %s ssid %s" % (network_id, ssid))
    return True


def _set_wpa_network_password(console, network_id, password):
    console.write(
        ("wpa_cli set_network %s psk '\"%s\"'" % (network_id, password)).encode()
    )
    sleep(0.1)
    console.write(b"\r")
    sleep(0.1)
    data = console.read(1024)
    cmp = re.compile(b"\\r\\nOK").search(data)
    if cmp is None:
        print("Failed to set network %s password" % network_id)
        return False

    print("Set network %s password" % network_id)
    return True


def _enable_wpa_network(console, network_id):
    console.write(("wpa_cli select_network %s" % network_id).encode())
    sleep(0.1)
    console.write(b"\r")
    sleep(0.1)
    data = console.read(1024)
    cmp = re.compile(b"\\r\\nOK").search(data)
    if cmp is None:
        print("Failed to enable network %s" % network_id)
        return False

    print("Enabled network %s" % network_id)
    return True
