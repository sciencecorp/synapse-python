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
    unpair_parser.add_argument(
        "identifier",
        nargs="?",
        default=None,
        help="Serial or stored name of a device to forget, matched against "
        "~/.scifi-env. Works without reaching the device -- use this when the "
        "device is gone. If omitted, --uri is used to contact the device and "
        "look up its serial instead.",
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
    except KeyboardInterrupt:
        # Ctrl-C during the 10s Info call, before any code is on screen. Without
        # this the user gets a raw traceback; nothing has been requested of the
        # device yet, so there is nothing to withdraw.
        console.print("\n[yellow]Pairing cancelled. Nothing was saved.")
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

    # A positional identifier is a request to clean up local state without
    # touching the network at all -- this is the "device is gone" case, so it
    # takes priority even if --uri was also given.
    identifier = getattr(args, "identifier", None)
    if identifier:
        _unpair_by_identifier(console, identifier)
        return

    if not args.uri:
        console.print(
            "[yellow]Specify a device: `unpair <serial-or-name>` to remove a "
            "local entry, or `--uri <device>` to look one up by contacting it."
        )
        _print_stored_entries(console)
        return

    device = syn.Device(args.uri, args.verbose)
    try:
        info = device.rpc.Info(Empty(), timeout=10.0)
    except grpc.RpcError as e:
        console.print(f"[bold red]Could not reach the device: {e.details()}")
        console.print(
            "[dim]Run `unpair <serial-or-name>` to remove a local entry "
            "without contacting the device.[/dim]"
        )
        return

    _remove_and_report(console, info.serial, info.name)


def _unpair_by_identifier(console, identifier):
    """Forget a locally stored token, matched by serial or name -- no network."""
    tokens = auth.load_tokens()

    if identifier in tokens:
        _remove_and_report(console, identifier, tokens[identifier][0])
        return

    matches = [serial for serial, (name, _) in tokens.items() if name == identifier]
    if len(matches) == 1:
        serial = matches[0]
        _remove_and_report(console, serial, tokens[serial][0])
        return

    if not matches:
        console.print(f"[bold red]No stored entry matches '{identifier}'.")
        _print_stored_entries(console)
        return

    console.print(
        f"[bold red]'{identifier}' matches more than one stored device; "
        "re-run with the serial, which is unique:"
    )
    for serial in matches:
        console.print(f"  [dim]{tokens[serial][0]}  (serial {serial})[/dim]")


def _print_stored_entries(console):
    tokens = auth.load_tokens()
    if not tokens:
        console.print("[dim]No devices are currently paired.[/dim]")
        return
    console.print("[dim]Stored entries:[/dim]")
    for serial, (name, _) in sorted(tokens.items()):
        console.print(f"  [dim]{name}  (serial {serial})[/dim]")


def _remove_and_report(console, serial, name):
    if auth.remove_token(serial):
        console.print(f"[bold green]Forgot the token for {name} ({serial}).")
        console.print(
            "[dim]The device still lists this client as paired. Removing it there is "
            "not yet supported.[/dim]"
        )
    else:
        console.print(f"[yellow]No stored token for {name} ({serial}).")
