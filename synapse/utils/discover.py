from dataclasses import dataclass
import time
import socket
import sys


BROADCAST_PORT = 6470
DISCOVERY_TIMEOUT_SEC = 10


@dataclass
class DeviceInfo:
    host: str
    port: int
    capability: str
    name: str
    serial: str


def discover_iter(socket_timeout_sec=1, discovery_timeout_sec=DISCOVERY_TIMEOUT_SEC):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if sys.platform != "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.settimeout(socket_timeout_sec)
    sock.bind(("", BROADCAST_PORT))

    devices = []  # Keep track of what we've seen to avoid duplicates
    try:
        start_time = time.time()

        while True:
            now = time.time()
            if now - start_time > discovery_timeout_sec:
                break
            try:
                data, server = sock.recvfrom(1024)
            except socket.timeout:
                continue
            else:
                data = data.decode("ascii").split()
                if data[0] == "ID":
                    if len(data) != 5:
                        continue
                    _, serial, capability, port, name = data
                    dev_info = DeviceInfo(
                        server[0], int(port), capability, name, serial
                    )
                    if dev_info not in devices:
                        devices.append(dev_info)
                        yield dev_info
    finally:
        sock.close()


def discover(timeout_sec=DISCOVERY_TIMEOUT_SEC):
    return list(discover_iter(timeout_sec))


def find_device_by_name(name, console, include_rpc_port=False):
    """Find a device by name using the discovery process."""
    with console.status(
        f"Searching for device with name {name}...", spinner="bouncingBall"
    ):
        # We are broadcasting data every 1 second
        socket_timeout_sec = 1
        discovery_timeout_sec = 5
        found_devices = []
        devices = discover_iter(socket_timeout_sec, discovery_timeout_sec)
        for device in devices:
            if device.name.lower() == name.lower():
                if include_rpc_port:
                    return f"{device.host}:{device.port}"
                return f"{device.host}"
            found_devices.append(device)

    console.print(f"[bold red]Device with name {name} not found")
    console.print(
        "[bold red]Either the device is not running or the name is incorrect\n"
    )
    if found_devices:
        console.print("[yellow]We did find some devices:")
        for device in found_devices:
            console.print(f"[yellow]{device.name} ({device.host})")
    return None
