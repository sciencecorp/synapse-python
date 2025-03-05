import os
import paramiko
import argparse
import stat
from rich.console import Console
from rich.table import Table
from rich import progress

import synapse.client.sftp as sftp
from synapse.utils.file import * 

SCIFI_DEFAULT_SFTP_USER = "scifi-sftp"
SCIFI_DEFAULT_SFTP_PASS = "axon"

def add_user_arguments(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--username",
        "-u",
        type=str,
        default=SCIFI_DEFAULT_SFTP_USER,
        help="Username for SFTP connection",
    )
    parser.add_argument(
        "--password",
        "-p",
        type=str,
        default=SCIFI_DEFAULT_SFTP_PASS,
        help="Password for SFTP connection",
    )

def add_commands(subparsers: argparse._SubParsersAction):
    file_parser = subparsers.add_parser("file", help="File commands")
    file_subparsers = file_parser.add_subparsers(title="File Commands")
    a = file_subparsers.add_parser("ls", help="List files on device")
    a.add_argument("uri", type=str)
    a.add_argument("path", type=str, nargs="?", default="/")
    add_user_arguments(a)
    a.set_defaults(func=ls)

    b: argparse.ArgumentParser = file_subparsers.add_parser("get", help="Get a file from device")
    b.add_argument("uri", type=str)
    b.add_argument("remote_path", type=str)
    b.add_argument("--output_path", "-o", type=str, default=os.getcwd(), required=False)
    b.add_argument("--recursive", "-r", action="store_true", help="Download directories recursively")
    add_user_arguments(b)
    b.set_defaults(func=get)

    c = file_subparsers.add_parser("rm", help="Remove a file from device")
    c.add_argument("uri", type=str)
    c.add_argument("path", type=str)
    add_user_arguments(c)
    c.set_defaults(func=rm)

def ls(args):
    console = Console()
    with console.status("Connecting to Synapse device...", spinner="bouncingBall"):
        ssh, sftp_conn = sftp.connect_sftp(args.uri, args.username, args.password)
    
    if ssh is None or sftp_conn is None:
        console.print(f"[bold red]Failed to connect to {args.uri}[/bold red]")
        return
    console.print(f"\n[bold blue]Listing directory:[/bold blue] [yellow]{args.path}[/yellow]\n")
    file_attr = sftp_conn.listdir_attr(args.path)
    print_file_list(file_attr, console)

    sftp.close_sftp(ssh, sftp_conn)

def get(args):
    console = Console()
    # validate_output_path(args.output_path, console)
    with console.status("Connecting to Synapse device...", spinner="bouncingBall"):
        ssh, sftp_conn = sftp.connect_sftp(args.uri, args.username, args.password)
    
    if ssh is None or sftp_conn is None:
        console.print(f"[bold red]Failed to connect to {args.uri}[/bold red]")
        return
    
    if args.recursive:
        get_dir(sftp_conn, args.remote_path, args.output_path, console)
    else:  
        get_file(sftp_conn, args.remote_path, args.output_path, console)

def rm(args):
    print(f"Removing file from {args.uri}")

def print_file_list(files: list[paramiko.SFTPAttributes], console: Console):
    # Sort files: directories first, then by name
    files.sort(key=lambda f: (0 if hasattr(f, 'st_mode') and f.st_mode & 0o40000 else 1, f.filename))
    
    # Create a table
    table = Table(show_header=True)
    table.add_column("Permissions", style="cyan")
    table.add_column("Size", justify="right", style="magenta")
    table.add_column("Date modified", style="yellow")
    table.add_column("Filename", style="white")
    for file_attr in files:
        # Get file mode and format it
        mode = format_mode(file_attr.st_mode if hasattr(file_attr, 'st_mode') else None)
        
        # Get owner and group (might not be available on all SFTP servers)
        owner = file_attr.st_uid if hasattr(file_attr, 'st_uid') else ''
        group = file_attr.st_gid if hasattr(file_attr, 'st_gid') else ''
        
        # Size formatting (human-readable using Rich's filesize)
        size = file_attr.st_size if hasattr(file_attr, 'st_size') else 0
        size_str = filesize_binary(size)
        
        # Time formatting
        mtime = file_attr.st_mtime if hasattr(file_attr, 'st_mtime') else None
        time_str = format_time(mtime)
        
        # Determine filename style based on type
        filename = file_attr.filename
        is_dir = stat.S_ISDIR(file_attr.st_mode)
        is_link = stat.S_ISLNK(file_attr.st_mode)
        is_executable = hasattr(file_attr, 'st_mode') and file_attr.st_mode & 0o100
        
        if is_dir:
            filename_styled = f"[bold blue]{filename}/[/bold blue]"
        elif is_link:
            filename_styled = f"[cyan]{filename}@[/cyan]"
        elif is_executable:
            filename_styled = f"[bold green]{filename}*[/bold green]"
        else:
            filename_styled = filename
        
        # Add row to table
        table.add_row(mode, size_str, time_str, filename_styled)
    
    # Print the table
    console.print(table)

def validate_output_path(output_path: str, console: Console):
    output_abs_path = os.path.abspath(output_path)
    output_dir = os.path.dirname(output_abs_path)
    if not os.path.exists(output_dir):
        console.print(f"[bold red]Output directory does not exist:[/bold red] [bold blue]{output_dir}")
        return

def get_dir(sftp_conn: paramiko.SFTPClient, remote_path: str, output_path: str, console: Console): 
    try:
        dir_attrs = sftp_conn.stat(remote_path)
    except FileNotFoundError:
        console.print(f"[bold red]Directory not found:[/bold red] [bold blue]{remote_path}")
        return
    if not stat.S_ISDIR(dir_attrs.st_mode):
        get_file(sftp_conn, remote_path, output_path, console)
        return

    output_path = os.path.join(output_path, os.path.basename(remote_path))
    local_dir = os.path.dirname(output_path)
    try:
        if local_dir != "":
            os.makedirs(local_dir, exist_ok=True)
    except OSError as e:
        console.print(f"[bold red]Failed to create output directory:[/bold red] {local_dir}")
        return
    
    file_list = sftp_conn.listdir(remote_path)
    
    for file in file_list:
        remote_file = os.path.join(remote_path, file)
        local_file = os.path.join(output_path, file)
        if stat.S_ISDIR(sftp_conn.stat(remote_file).st_mode):
            get_dir(sftp_conn, remote_file, local_file, console)
        else:
            get_file(sftp_conn, remote_file, local_file, console)

def get_file(sftp_conn: paramiko.SFTPClient, remote_path: str, output_path: str, console: Console):
    try:
        is_dir = stat.S_ISDIR(sftp_conn.stat(remote_path).st_mode)
    except FileNotFoundError:
        console.print(f"[bold red]File not found:[/bold red] [bold blue]{remote_path}")
        return
    
    if is_dir:
        console.print(f"[bold yellow]Requested path: [/bold yellow][blue]{remote_path}[/blue][bold yellow] is a directory. Use the --recursive flag to download directories.")
        return

    local_dir = os.path.dirname(output_path)
    try:
        if local_dir != "":
            os.makedirs(local_dir, exist_ok=True)
    except OSError as e:
        console.print(f"[bold red]Failed to create output directory:[/bold red] {local_dir}")
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
            progress.TimeElapsedColumn() 
        )
        with prog:
            task = prog.add_task(f"Downloading file: {remote_path}", total=file_size)
            def update_progress(transferred: int, total: int):
                prog.update(task, completed=transferred)
            sftp_conn.get(remote_path, local_path, callback=update_progress)
    except paramiko.SFTPError as e:
        console.print(f"[bold red]Failed to download file:[/bold red] {e}")
        return
    