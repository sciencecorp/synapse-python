import os
import paramiko
import argparse
import stat
import yaml
import getpass
from typing import Optional
import paramiko.ssh_exception
from rich.console import Console
from rich.table import Table
from rich import progress
from rich.prompt import Confirm

from synapse import Device
import synapse.client.sftp as sftp
from synapse.utils.file import format_mode, format_time, filesize_binary

SCIFI_DEFAULT_SFTP_USER = "scifi-sftp"
DEFAULT_ENV_FILE = ".scienv"


def add_user_arguments(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--username",
        "-u",
        type=str,
        default=SCIFI_DEFAULT_SFTP_USER,
        help="Username for SFTP connection",
    )
    parser.add_argument(
        "--env-file",
        "-e",
        type=str,
        default=DEFAULT_ENV_FILE,
        help="Path to environment file containing passwords",
    )
    parser.add_argument(
        "--forget-password",
        "-f",
        action="store_true",
        help="Dont store an input password locally for future use",
    )


def add_commands(subparsers: argparse._SubParsersAction):
    file_parser = subparsers.add_parser("file", help="File commands")
    file_subparsers = file_parser.add_subparsers(title="File Commands")
    a: argparse.ArgumentParser = file_subparsers.add_parser(
        "ls", help="List files on device"
    )
    a.add_argument(
        "path", type=str, nargs="?", default="/", help="Path to list files from"
    )
    add_user_arguments(a)
    a.set_defaults(func=ls)

    b: argparse.ArgumentParser = file_subparsers.add_parser(
        "get", help="Get a file from device"
    )
    b.add_argument("remote_path", type=str, help="Remote path of file to download")
    b.add_argument(
        "--output_path",
        "-o",
        type=str,
        default=os.getcwd(),
        help="Output path for downloaded file(s)",
    )
    b.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Download directories recursively",
    )
    add_user_arguments(b)
    b.set_defaults(func=get)

    c: argparse.ArgumentParser = file_subparsers.add_parser(
        "rm", help="Remove a file from device"
    )
    c.add_argument("path", type=str, help="Path to file to remove")
    c.add_argument(
        "--recursive", "-r", action="store_true", help="Remove directories recursively"
    )
    add_user_arguments(c)
    c.set_defaults(func=rm)


def ls(args):
    console = Console()
    connections = setup_connection(
        args.uri,
        args.username,
        args.env_file,
        args.forget_password,
        console,
    )
    if connections is None:
        return
    ssh, sftp_conn = connections
    console.print(
        f"\n[bold blue]Listing directory:[/bold blue] [yellow]{args.path}[/yellow]\n"
    )

    try:
        file_attr = sftp_conn.listdir_attr(args.path)
        print_file_list(file_attr, console)
    except Exception as e:
        console.print(f"[bold red]Failed to list directory:[/bold red] {e}")

    sftp.close_sftp(ssh, sftp_conn)


def get(args):
    console = Console()
    connections = setup_connection(
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
        get_dir(sftp_conn, args.remote_path, args.output_path, console)
    else:
        get_file(sftp_conn, args.remote_path, args.output_path, console)

    sftp.close_sftp(ssh, sftp_conn)


def rm(args):
    console = Console()
    connections = setup_connection(
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


def setup_connection(
    uri: str,
    username: str,
    env_file: str,
    forget_password: bool,
    console: Console,
) -> Optional[tuple[paramiko.SSHClient, paramiko.SFTPClient]]:
    dev_name = Device(uri).get_name()
    password = find_password(
        dev_name, env_file
    )  # Check if password is provided or stored in env file
    if password is None:
        console.print(f"[bold red]Didnt find any password for {uri}[/bold red]")
        return

    # Open SFTP connection
    with console.status("Connecting to Synapse device...", spinner="bouncingBall"):
        try:
            ssh, sftp_conn = sftp.connect_sftp(uri, username, password)
        except paramiko.ssh_exception.AuthenticationException:
            console.print(f"[bold red]Authentication failed for {uri}[/bold red]")
            console.print("[yellow] Incorrect username or password.")
            return None
    if ssh is None or sftp_conn is None:
        console.print(f"[bold red]Failed to connect to {uri}[/bold red]")
        return
    # If the connection is successful, we can prompt the user if they want to save the password
    if not forget_password and dev_name is not None:
        save_password(password, env_file, dev_name)
    return ssh, sftp_conn


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
    sftp_conn: paramiko.SFTPClient, remote_path: str, output_path: str, console: Console
):
    try:
        dir_attrs = sftp_conn.stat(remote_path)
    except FileNotFoundError:
        console.print(
            f"[bold red]Directory not found:[/bold red] [bold blue]{remote_path}"
        )
        return
    if not stat.S_ISDIR(dir_attrs.st_mode):
        get_file(sftp_conn, remote_path, output_path, console)
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
            get_dir(sftp_conn, remote_file, local_file, console)
        else:
            get_file(sftp_conn, remote_file, local_file, console)


def get_file(
    sftp_conn: paramiko.SFTPClient, remote_path: str, output_path: str, console: Console
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
            task = prog.add_task(f"Downloading file: {remote_path}", total=file_size)

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


def find_password(dev_name: Optional[str], env_file: Optional[str]):
    password = None
    if env_file is not None and dev_name is not None:
        if os.path.exists(env_file):
            password = load_pass_from_env_file(env_file, dev_name)
            if password is not None:
                return password
    password = getpass.getpass("Enter password: ")
    return password


def save_password(password: str, env_file: str, device_name: str):
    if env_file is None or device_name is None or password is None:
        return
    if os.path.exists(env_file):
        if load_pass_from_env_file(env_file, device_name) is not None:
            return

    save_pass = Confirm.ask(f"Save password for {device_name} in {env_file}?")
    if not save_pass:
        return
    store_pass_to_env_file(env_file, device_name, password)


def load_pass_from_env_file(env_file: str, device_name: str) -> Optional[str]:
    try:
        with open(env_file, "r") as f:
            env_loaded = yaml.safe_load(f)
            if env_loaded is None:
                return None
            if "sftp_passwords" not in env_loaded:
                return None
            passwords = env_loaded.get("sftp_passwords", {})
            if device_name in passwords:
                try:
                    stored_pass = passwords[device_name]
                    return stored_pass
                except Exception:
                    print(
                        f"Couldnt read password for {device_name} from env file. Env file may be improperly formatted."
                    )
                    return None
            else:
                return None
    except Exception as e:
        print(f"Couldnt read env file at: {env_file}. {e}")
    return None


# Store password to the .env file in yaml format
def store_pass_to_env_file(env_file: str, device_name: str, password: str):
    try:
        prev_env = {}
        if os.path.exists(env_file):
            with open(env_file, "r") as f:
                prev_env = yaml.safe_load(f)
                prev_env = prev_env if prev_env is not None else {}
        passwords = prev_env.get("sftp_passwords", {})
        passwords[device_name] = password
        prev_env["sftp_passwords"] = passwords
        with open(env_file, "w", encoding="utf8") as f:
            yaml.dump(prev_env, f, default_flow_style=False)
    except TypeError:
        print(
            f"Failed to store pass to env file at: {env_file}. Env file may be improperly formatted."
        )
    except Exception as e:
        print(f"Failed to store pass to env file at: {env_file}. {e}")
