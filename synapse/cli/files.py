"""`synapsectl file` -- device files over gRPC.

This used SFTP, which needed its own password: a device carried two
independent credentials, and `synapsectl file` was the only command that asked
for one. Going through the SynapseDevice service means file access is governed
by the same pairing token as everything else, so the SFTP password is gone --
along with --username, --env-file and the local password store.

Paths are relative to the device's data root and cannot escape it, so
`file ls /` shows the data root. That is the same tree the scifi-sftp account
was chrooted to, so what you can reach is unchanged -- only the credential is.
"""

import argparse
import os
from typing import List, Optional

import grpc
from rich import progress
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from synapse import Device
from synapse.api.files_pb2 import ListFilesResponse
from synapse.client import files as files_client
from synapse.utils.file import filesize_binary, format_time

# Accepted and ignored so a script written against the SFTP version fails
# loudly on the flag being pointless rather than confusingly on an unknown
# argument. Hidden from --help, which advertises only what still does anything.
_RETIRED_SFTP_FLAGS = ("username", "env_file", "forget_password")


def _add_retired_sftp_flags(parser: argparse.ArgumentParser):
    parser.add_argument("--username", "-u", type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--env-file", "-e", type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--forget-password", "-f", action="store_true", help=argparse.SUPPRESS
    )


def _warn_about_retired_flags(args, console: Console):
    used = [
        f.replace("_", "-")
        for f in _RETIRED_SFTP_FLAGS
        if getattr(args, f, None) not in (None, False)
    ]
    if used:
        console.print(
            f"[yellow]Ignoring {', '.join('--' + u for u in used)}:[/yellow] file "
            "transfers no longer use SFTP, so there is no separate password. "
            "Access is granted by pairing with the device."
        )


def add_commands(subparsers: argparse._SubParsersAction):
    file_parser = subparsers.add_parser("file", help="File commands")
    file_subparsers = file_parser.add_subparsers(title="File Commands")

    a = file_subparsers.add_parser("ls", help="List files on device")
    a.add_argument(
        "path", type=str, nargs="?", default="", help="Path to list, relative to the data directory"
    )
    a.add_argument(
        "--recursive", "-r", action="store_true", help="List subdirectories too"
    )
    _add_retired_sftp_flags(a)
    a.set_defaults(func=ls)

    b = file_subparsers.add_parser("get", help="Get a file from device")
    b.add_argument("remote_path", type=str, help="Remote path of file to download")
    b.add_argument(
        "--output_path", "-o", type=str, default=os.getcwd(), help="Output path for downloaded file(s)"
    )
    b.add_argument(
        "--recursive", "-r", action="store_true", help="Download directories recursively"
    )
    b.add_argument(
        "--no-resume",
        action="store_true",
        help="Download from the start instead of continuing a partial file",
    )
    _add_retired_sftp_flags(b)
    b.set_defaults(func=get)

    c = file_subparsers.add_parser("put", help="Upload a file to the device")
    c.add_argument("local_path", type=str, help="Local file to upload")
    c.add_argument(
        "remote_path",
        type=str,
        nargs="?",
        default=None,
        help="Remote path, relative to the data directory (default: the name as given)",
    )
    c.add_argument(
        "--recursive", "-r", action="store_true", help="Upload a directory recursively"
    )
    c.set_defaults(func=put)

    d = file_subparsers.add_parser("rm", help="Remove a file from device")
    d.add_argument("path", type=str, help="Path to file to remove")
    d.add_argument(
        "--recursive", "-r", action="store_true", help="Remove directories recursively"
    )
    d.add_argument(
        "--yes", "-y", action="store_true", help="Do not ask before deleting"
    )
    _add_retired_sftp_flags(d)
    d.set_defaults(func=rm)


def _rpc_error(console: Console, action: str, e: grpc.RpcError) -> None:
    """One place for gRPC failures, so every command explains them the same way."""
    code = e.code()
    if code == grpc.StatusCode.UNAUTHENTICATED:
        console.print(
            f"[bold red]Not paired with this device.[/bold red] Run "
            f"[bold]synapsectl pair[/bold] first."
        )
    elif code == grpc.StatusCode.UNIMPLEMENTED:
        console.print(
            "[bold red]This device's firmware does not support file transfers "
            "over gRPC.[/bold red] Update the device firmware and try again."
        )
    elif code == grpc.StatusCode.INVALID_ARGUMENT:
        console.print(f"[bold red]{e.details()}[/bold red]")
    elif code == grpc.StatusCode.NOT_FOUND:
        console.print("[bold red]No such file on the device.[/bold red]")
    else:
        console.print(f"[bold red]Failed to {action}:[/bold red] {e.details()}")


def _print_file_list(files: List[ListFilesResponse.File], console: Console):
    # Directories first, then by name -- same ordering the SFTP version used.
    entries = sorted(files, key=lambda f: (0 if f.is_dir else 1, f.path))

    table = Table(show_header=True)
    table.add_column("Size", justify="right", style="magenta")
    table.add_column("Date modified", style="yellow")
    table.add_column("Filename", style="white")
    for f in entries:
        size_str = "" if f.is_dir else filesize_binary(f.size)
        name = f"[bold blue]{f.path}/[/bold blue]" if f.is_dir else f.path
        table.add_row(size_str, format_time(f.modified), name)

    console.print(table)
    if not entries:
        console.print("[dim](empty)[/dim]")


def ls(args):
    console = Console()
    _warn_about_retired_flags(args, console)
    device = Device(args.uri, args.verbose)
    shown = args.path or "/"
    console.print(f"\n[bold blue]Listing directory:[/bold blue] [yellow]{shown}[/yellow]\n")
    try:
        _print_file_list(files_client.list_files(device, args.path, args.recursive), console)
    except grpc.RpcError as e:
        _rpc_error(console, "list the directory", e)


def _download_one(device, console: Console, remote: str, local: str, resume: bool) -> bool:
    with progress.Progress(
        progress.TextColumn("[cyan]{task.description}"),
        progress.BarColumn(),
        progress.DownloadColumn(),
        progress.TransferSpeedColumn(),
        progress.TimeRemainingColumn(),
        console=console,
    ) as bar:
        task = bar.add_task(os.path.basename(remote), total=None)

        def on_progress(done: int, total: int):
            # The device reports the total on every chunk, so it is only known
            # once the first one lands.
            bar.update(task, completed=done, total=total or None)

        try:
            files_client.read_file(device, remote, local, progress=on_progress, resume=resume)
            return True
        except grpc.RpcError as e:
            _rpc_error(console, f"download {remote}", e)
            return False


def get(args):
    console = Console()
    _warn_about_retired_flags(args, console)
    device = Device(args.uri, args.verbose)
    resume = not args.no_resume

    if not args.recursive:
        local = args.output_path
        if os.path.isdir(local):
            local = os.path.join(local, os.path.basename(args.remote_path))
        if _download_one(device, console, args.remote_path, local, resume):
            console.print(f"[bold green]Saved[/bold green] {local}")
        return

    try:
        entries = files_client.list_files(device, args.remote_path, recursive=True)
    except grpc.RpcError as e:
        _rpc_error(console, "list the directory", e)
        return

    wanted = [f for f in entries if not f.is_dir]
    if not wanted:
        console.print("[yellow]Nothing to download.[/yellow]")
        return

    ok = 0
    for f in wanted:
        # Mirror the device's layout under the output directory. relpath keeps
        # the tree shape without embedding the parent's name twice.
        rel = os.path.relpath(f.path, args.remote_path) if args.remote_path else f.path
        local = os.path.join(args.output_path, os.path.basename(args.remote_path.rstrip("/")) or "", rel)
        if _download_one(device, console, f.path, local, resume):
            ok += 1
    console.print(f"[bold green]Downloaded {ok}/{len(wanted)} file(s)[/bold green] to {args.output_path}")


def _remote_is_dir(device, path: str) -> bool:
    """Whether `path` already exists on the device as a directory.

    Listing the parent and looking for the entry, rather than listing `path`
    itself: an empty directory and a missing path both list as nothing, so
    listing the target cannot tell them apart.
    """
    cleaned = path.rstrip("/")
    if not cleaned:
        return True  # the data root itself
    try:
        entries = files_client.list_files(device, os.path.dirname(cleaned))
    except grpc.RpcError:
        return False
    name = os.path.basename(cleaned)
    return any(os.path.basename(f.path) == name and f.is_dir for f in entries)


def _upload_one(device, console: Console, local: str, remote: str) -> Optional[int]:
    with progress.Progress(
        progress.TextColumn("[cyan]{task.description}"),
        progress.BarColumn(),
        progress.DownloadColumn(),
        progress.TransferSpeedColumn(),
        console=console,
    ) as bar:
        task = bar.add_task(os.path.basename(local), total=os.path.getsize(local))
        try:
            return files_client.write_file(
                device,
                local,
                remote,
                progress=lambda done, tot: bar.update(task, completed=done),
            )
        except grpc.RpcError as e:
            _rpc_error(console, f"upload {local}", e)
            return None


def put(args):
    console = Console()
    device = Device(args.uri, args.verbose)
    local = args.local_path.rstrip("/")

    if os.path.isdir(local):
        if not args.recursive:
            console.print(
                f"[bold red]{local} is a directory.[/bold red] Pass --recursive to upload it."
            )
            return
        base = args.remote_path or os.path.basename(local)
        # No mkdir needed: the server creates parent directories for whatever
        # path a chunk stream names, so the tree appears as the files land.
        files = [
            os.path.join(root, name)
            for root, _, names in os.walk(local)
            for name in names
        ]
        if not files:
            console.print("[yellow]Nothing to upload.[/yellow]")
            return
        ok = 0
        for f in sorted(files):
            remote = os.path.join(base, os.path.relpath(f, local))
            if _upload_one(device, console, f, remote) is not None:
                ok += 1
        console.print(f"[bold green]Uploaded {ok}/{len(files)} file(s)[/bold green] to {base}")
        return

    if not os.path.isfile(local):
        console.print(f"[bold red]No such local file:[/bold red] {local}")
        return
    remote = args.remote_path or os.path.basename(local)
    # `put file some/dir` means into that directory, the same way
    # `get file -o some/dir` does. Without this the server is asked to replace
    # a directory with a file, which cannot work.
    if _remote_is_dir(device, remote):
        remote = os.path.join(remote.rstrip("/"), os.path.basename(local))
    written = _upload_one(device, console, local, remote)
    if written is not None:
        console.print(f"[bold green]Uploaded[/bold green] {written} bytes to {remote}")


def rm(args):
    console = Console()
    _warn_about_retired_flags(args, console)
    device = Device(args.uri, args.verbose)

    # Recursive deletes take a whole recording directory with them, and there
    # is no undo on the device.
    if args.recursive and not args.yes:
        if not Confirm.ask(f"Delete [bold]{args.path}[/bold] and everything under it?"):
            console.print("Not deleting.")
            return

    try:
        files_client.delete_file(device, args.path, args.recursive)
    except grpc.RpcError as e:
        _rpc_error(console, f"delete {args.path}", e)
        return
    console.print(f"[bold green]Deleted[/bold green] {args.path}")
