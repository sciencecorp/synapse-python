import getpass
import logging
import socket

import grpc
from google.protobuf.empty_pb2 import Empty
from rich.console import Console

import synapse as syn
from synapse.api.auth_pb2 import AuthRequest
from synapse.client import auth

logger = logging.getLogger(__name__)


def add_commands(subparsers):
    pair_parser = subparsers.add_parser(
        "pair", help="Request access to a device, approved on the device screen"
    )
    pair_parser.add_argument(
        "--label",
        help="How this machine identifies itself on the device screen "
        "(default: user@hostname)",
        default=None,
    )
    pair_parser.set_defaults(func=pair)

    unpair_parser = subparsers.add_parser(
        "unpair", help="Forget the locally stored token for a device"
    )
    unpair_parser.set_defaults(func=unpair)


def _default_label() -> str:
    try:
        return f"{getpass.getuser()}@{socket.gethostname()}"
    except Exception:
        return "unidentified client"


def pair(args):
    console = Console()
    device = syn.Device(args.uri, args.verbose)

    # Info is open, so this works before pairing. It gives us the serial to key
    # the token on and the name to show the user.
    try:
        info = device.rpc.Info(Empty(), timeout=10.0)
    except grpc.RpcError as e:
        console.print(f"[bold red]Could not reach the device: {e.details()}")
        return

    if not info.serial:
        console.print("[bold red]This device did not report a serial number; cannot pair.")
        return

    label = args.label or _default_label()

    try:
        stream = device.rpc.RequestAuth(AuthRequest(client_label=label))

        challenge_event = next(stream)
        if not challenge_event.HasField("challenge"):
            console.print("[bold red]Unexpected response from the device.")
            return
        code = challenge_event.challenge.code
        expires_in = challenge_event.challenge.expires_in_sec

        console.print()
        console.print(f"  Pairing code: [bold cyan]{code}[/bold cyan]")
        console.print()
        console.print(
            f"Check the screen on [bold]{info.name}[/bold]. If it shows the same code, "
            f"tap Allow."
        )
        console.print(f"[dim]This request expires in {expires_in} seconds.[/dim]")
        console.print()

        with console.status("Waiting for approval on the device", spinner="bouncingBall"):
            result_event = next(stream)

        if not result_event.HasField("result"):
            console.print("[bold red]Unexpected response from the device.")
            return

        result = result_event.result
        if not result.granted:
            console.print(f"[bold red]Not paired: {result.reason}")
            return

        auth.save_token(info.serial, info.name, result.token)
        console.print(
            f"[bold green]Paired with {info.name} ({info.serial}).[/bold green] "
            f"Token saved to {auth.env_file_path()}"
        )

    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNIMPLEMENTED:
            console.print(
                "[bold red]This device's firmware does not support pairing. "
                "Update the device firmware and try again."
            )
        elif e.code() == grpc.StatusCode.FAILED_PRECONDITION:
            console.print(f"[bold red]{e.details()}. Try again in a moment.")
        else:
            console.print(f"[bold red]Pairing failed: {e.details()}")
    except KeyboardInterrupt:
        console.print("\n[yellow]Pairing cancelled. Nothing was saved.")


def unpair(args):
    console = Console()
    device = syn.Device(args.uri, args.verbose)

    try:
        info = device.rpc.Info(Empty(), timeout=10.0)
        serial = info.serial
        name = info.name
    except grpc.RpcError:
        # The device may be gone; fall back to matching what we have locally.
        console.print("[yellow]Could not reach the device; looking up local entries.")
        serial = None
        name = args.uri

    if not serial:
        matches = [s for s, (n, _) in auth.load_tokens().items() if n == args.uri]
        if len(matches) != 1:
            console.print(
                "[bold red]Could not determine which device to unpair. "
                f"Local entries: {list(auth.load_tokens().keys())}"
            )
            return
        serial = matches[0]

    if auth.remove_token(serial):
        console.print(f"[bold green]Forgot the token for {name} ({serial}).")
        console.print(
            "[dim]The device still lists this client as paired. Removing it there is "
            "not yet supported.[/dim]"
        )
    else:
        console.print(f"[yellow]No stored token for {name} ({serial}).")
