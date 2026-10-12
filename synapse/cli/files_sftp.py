"""synapsectl file over SFTP, for device firmware that predates pairing.

Older firmware has no file RPCs, only the scifi-sftp account and its own
password. This is the SFTP implementation synapsectl shipped before the move
to gRPC, kept so a newer synapsectl still works with those devices; files.py
calls into it when the device answers the file RPCs with UNIMPLEMENTED.
"""

import os
import stat

import paramiko
from rich import progress
from rich.console import Console
from rich.table import Table

import synapse.client.sftp as sftp
from synapse.utils.file import filesize_binary, format_mode, format_time

SCIFI_DEFAULT_SFTP_USER = "scifi-sftp"
DEFAULT_ENV_FILE = ".scienv"


def ls(args):
    console = Console()
    connections = sftp.setup_connection(
        args.uri,
        args.username,
        args.env_file,
        args.forget_password,
        console,
    )
    if connections is None:
        return
    ssh, sftp_conn = connections
    # The shared ls parser defaults to "" (the gRPC data root); SFTP needs "/".
    path = args.path or "/"
    console.print(
        f"\n[bold blue]Listing directory:[/bold blue] [yellow]{path}[/yellow]\n"
    )

    try:
        file_attr = sftp_conn.listdir_attr(path)
        print_file_list(file_attr, console)
    except Exception as e:
        console.print(f"[bold red]Failed to list directory:[/bold red] {e}")

    sftp.close_sftp(ssh, sftp_conn)


def get(args):
    console = Console()
    connections = sftp.setup_connection(
        args.uri,
        args.username,
        args.env_file,
        args.forget_password,
        console,
    )
    if connections is None:
        return
    ssh, sftp_conn = connections

    if args.recursive:
        get_dir(sftp_conn, args.remote_path, args.output_path, console, args.yes)
    else:
        get_file(sftp_conn, args.remote_path, args.output_path, console, args.yes)

    sftp.close_sftp(ssh, sftp_conn)


def rm(args):
    console = Console()
    connections = sftp.setup_connection(
        args.uri,
        args.username,
        args.env_file,
        args.forget_password,
        console,
    )
    if connections is None:
        return
    ssh, sftp_conn = connections

    remove_file(sftp_conn, args.path, args.recursive, console)
    sftp.close_sftp(ssh, sftp_conn)


def print_file_list(files: list[paramiko.SFTPAttributes], console: Console):
    # Sort files: directories first, then by name
    files.sort(
        key=lambda f: (
            0 if hasattr(f, "st_mode") and f.st_mode & 0o40000 else 1,
            f.filename,
        )
    )

    table = Table(show_header=True)
    table.add_column("Permissions", style="cyan")
    table.add_column("Size", justify="right", style="magenta")
    table.add_column("Date modified", style="yellow")
    table.add_column("Filename", style="white")
    for file_attr in files:
        # Get file mode and format it
        mode = format_mode(file_attr.st_mode if hasattr(file_attr, "st_mode") else None)

        # Filesize
        size = file_attr.st_size if hasattr(file_attr, "st_size") else 0
        size_str = filesize_binary(size)

        # Time modified
        mtime = file_attr.st_mtime if hasattr(file_attr, "st_mtime") else None
        time_str = format_time(mtime)

        # Determine filename style based on type
        filename = file_attr.filename
        is_dir = stat.S_ISDIR(file_attr.st_mode)
        is_link = stat.S_ISLNK(file_attr.st_mode)
        is_executable = hasattr(file_attr, "st_mode") and file_attr.st_mode & 0o100

        if is_dir:
            filename_styled = f"[bold blue]{filename}/[/bold blue]"
        elif is_link:
            filename_styled = f"[cyan]{filename}@[/cyan]"
        elif is_executable:
            filename_styled = f"[bold green]{filename}*[/bold green]"
        else:
            filename_styled = filename

        table.add_row(mode, size_str, time_str, filename_styled)

    console.print(table)


def get_dir(
    sftp_conn: paramiko.SFTPClient,
    remote_path: str,
    output_path: str,
    console: Console,
    overwrite: bool = False,
):
    try:
        dir_attrs = sftp_conn.stat(remote_path)
    except FileNotFoundError:
        console.print(
            f"[bold red]Directory not found:[/bold red] [bold blue]{remote_path}"
        )
        return
    if not stat.S_ISDIR(dir_attrs.st_mode):
        get_file(sftp_conn, remote_path, output_path, console, overwrite)
        return

    output_path = os.path.join(output_path, os.path.basename(remote_path))
    local_dir = os.path.dirname(output_path)
    try:
        if local_dir != "":
            os.makedirs(local_dir, exist_ok=True)
    except OSError:
        console.print(
            f"[bold red]Failed to create output directory:[/bold red] {local_dir}"
        )
        return

    file_list = sftp_conn.listdir(remote_path)

    for file in file_list:
        remote_file = os.path.join(remote_path, file)
        local_file = os.path.join(output_path, file)
        if stat.S_ISDIR(sftp_conn.stat(remote_file).st_mode):
            get_dir(sftp_conn, remote_file, local_file, console, overwrite)
        else:
            get_file(sftp_conn, remote_file, local_file, console, overwrite)


def get_file(
    sftp_conn: paramiko.SFTPClient,
    remote_path: str,
    output_path: str,
    console: Console,
    overwrite: bool = False,
):
    try:
        is_dir = stat.S_ISDIR(sftp_conn.stat(remote_path).st_mode)
    except FileNotFoundError:
        console.print(f"[bold red]File not found:[/bold red] [blue]{remote_path}")
        return

    if is_dir:
        console.print(
            f"[bold yellow]Requested path: [/bold yellow][blue]{remote_path}[/blue][bold yellow] is a directory. Use the --recursive(-r) flag to download directories."
        )
        return

    local_dir = os.path.dirname(output_path)
    try:
        if local_dir != "":
            os.makedirs(local_dir, exist_ok=True)
    except OSError:
        console.print(
            f"[bold red]Failed to create output directory:[/bold red] {local_dir}"
        )
        return

    local_path = output_path
    if os.path.isdir(output_path):
        local_path = os.path.join(output_path, os.path.basename(remote_path))
    if os.path.exists(local_path) and not overwrite and not _may_overwrite(console, local_path):
        return

    try:
        file_st_size = sftp_conn.stat(remote_path).st_size
        file_size = file_st_size if file_st_size is not None else 0

        prog = progress.Progress(
            progress.SpinnerColumn(),
            progress.TextColumn("[progress.description]{task.description}"),
            progress.BarColumn(),
            progress.DownloadColumn(),
            progress.TransferSpeedColumn(),
            progress.TimeElapsedColumn(),
        )
        with prog:
            task = prog.add_task(os.path.basename(remote_path), total=file_size)

            def update_progress(transferred: int, total: int):
                prog.update(task, completed=transferred)

            sftp_conn.get(remote_path, local_path, callback=update_progress)
    except paramiko.SFTPError as e:
        console.print(f"[bold red]Failed to download file:[/bold red] {e}")
        return


def remove_file(
    sftp_conn: paramiko.SFTPClient, remote_path: str, recursive: bool, console: Console
):
    try:
        is_dir = stat.S_ISDIR(sftp_conn.stat(remote_path).st_mode)
    except FileNotFoundError:
        console.print(f"[bold red]File not found:[/bold red] [blue]{remote_path}")
        return

    if is_dir and not recursive:
        console.print(
            f"[bold yellow]Requested path: [/bold yellow][blue]{remote_path}[/blue][bold yellow] is a directory. Use the --recursive(-r) flag to remove directories."
        )
        return

    try:
        if is_dir:
            file_list = sftp_conn.listdir(remote_path)
            for file in file_list:
                remote_file = os.path.join(remote_path, file)
                remove_file(sftp_conn, remote_file, recursive, console)
            sftp_conn.rmdir(remote_path)
        else:
            with console.status(
                f"Removing file: {remote_path}", spinner="bouncingBall"
            ):
                sftp_conn.remove(remote_path)
    except Exception as e:
        console.print(f"[bold red]Failed to remove file:[/bold red] {e}")
        return

    console.print(f"[bold green]File removed:[/bold green] [blue]{remote_path}")


def put(args):
    console = Console()
    connections = sftp.setup_connection(
        args.uri,
        args.username,
        args.env_file,
        args.forget_password,
        console,
    )
    if connections is None:
        return
    ssh, sftp_conn = connections

    local = args.local_path.rstrip("/")
    remote = args.remote_path or os.path.basename(local)
    try:
        if os.path.isdir(local):
            if not args.recursive:
                console.print(f"[bold red]{local} is a directory.[/bold red] Pass --recursive to upload it.")
                return
            for root, _, names in os.walk(local):
                for name in sorted(names):
                    path = os.path.join(root, name)
                    put_file(sftp_conn, path, os.path.join(remote, os.path.relpath(path, local)), console, args.yes)
        elif os.path.isfile(local):
            try:
                if stat.S_ISDIR(sftp_conn.stat(remote).st_mode):
                    remote = os.path.join(remote, os.path.basename(local))
            except FileNotFoundError:
                pass
            put_file(sftp_conn, local, remote, console, args.yes)
        else:
            console.print(f"[bold red]No such local file:[/bold red] {local}")
    finally:
        sftp.close_sftp(ssh, sftp_conn)


def _remote_exists(sftp_conn: paramiko.SFTPClient, path: str) -> bool:
    try:
        sftp_conn.stat(path)
        return True
    except FileNotFoundError:
        return False


def _may_overwrite(console: Console, what: str) -> bool:
    # Imported here: synapse.cli.files imports this module.
    from synapse.cli.files import _may_overwrite as ask

    return ask(console, what)


def _makedirs(sftp_conn: paramiko.SFTPClient, remote_dir: str):
    """mkdir -p over SFTP."""
    path = ""
    for part in [p for p in remote_dir.split("/") if p]:
        path = f"{path}/{part}" if path else (f"/{part}" if remote_dir.startswith("/") else part)
        try:
            sftp_conn.stat(path)
        except FileNotFoundError:
            sftp_conn.mkdir(path)


def put_file(
    sftp_conn: paramiko.SFTPClient,
    local_path: str,
    remote_path: str,
    console: Console,
    overwrite: bool = False,
):
    if not overwrite and _remote_exists(sftp_conn, remote_path) and not _may_overwrite(console, remote_path):
        return
    try:
        remote_dir = os.path.dirname(remote_path)
        if remote_dir:
            _makedirs(sftp_conn, remote_dir)
        prog = progress.Progress(
            progress.SpinnerColumn(),
            progress.TextColumn("[progress.description]{task.description}"),
            progress.BarColumn(),
            progress.DownloadColumn(),
            progress.TransferSpeedColumn(),
            progress.TimeElapsedColumn(),
        )
        with prog:
            task = prog.add_task(os.path.basename(local_path), total=os.path.getsize(local_path))
            sftp_conn.put(local_path, remote_path, callback=lambda done, _total: prog.update(task, completed=done))
        console.print(f"[bold green]Uploaded[/bold green] {local_path} to {remote_path}")
    except PermissionError:
        # The SFTP account is chrooted to the data directory, whose top level
        # it cannot write; only some folders under it are writable.
        console.print(
            f"[bold red]The device does not allow uploads to {remote_path}.[/bold red] "
            "On this firmware, upload into a folder such as disk_writer/ or models/."
        )
    except (OSError, paramiko.SFTPError) as e:
        console.print(f"[bold red]Failed to upload {local_path}:[/bold red] {e}")
