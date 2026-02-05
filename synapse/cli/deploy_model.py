"""CLI command for deploying models to Synapse devices."""

import argparse
import os
from typing import Optional

import paramiko.ssh_exception
from rich.console import Console
from rich import progress

import synapse.client.sftp as sftp
from synapse.cli.files import find_password, save_password
from synapse.utils.model_converter import convert_to_dlc

# Constants
DEVICE_MODEL_DIR = "/models"
DEFAULT_SFTP_USER = "scifi-sftp"
DEFAULT_ENV_FILE = ".scienv"


def add_commands(subparsers: argparse._SubParsersAction):
    """Add the deploy-model command to the CLI."""
    parser = subparsers.add_parser(
        "deploy-model",
        help="Deploy a machine learning model to a Synapse device",
    )

    parser.add_argument(
        "model_path",
        type=str,
        help="Path to the model file (.pt, .onnx, or .dlc)",
    )

    parser.add_argument(
        "--input-shape",
        type=str,
        default=None,
        help='Input shape for the model (e.g., "1,32,64"). Required if model has dynamic dimensions.',
    )

    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Model name on device (default: filename without extension)",
    )

    parser.add_argument(
        "--username",
        "-u",
        type=str,
        default=DEFAULT_SFTP_USER,
        help=f"SFTP username (default: {DEFAULT_SFTP_USER})",
    )

    parser.add_argument(
        "--env-file",
        "-e",
        type=str,
        default=DEFAULT_ENV_FILE,
        help=f"Password env file (default: {DEFAULT_ENV_FILE})",
    )

    parser.add_argument(
        "--forget-password",
        "-f",
        action="store_true",
        help="Don't store password locally",
    )

    parser.set_defaults(func=deploy_model)


def deploy_model(args):
    """Deploy a model to a Synapse device."""
    console = Console()

    # Validate model path
    if not os.path.exists(args.model_path):
        console.print(f"[bold red]Error:[/bold red] Model file not found: {args.model_path}")
        return

    # Parse input shape if provided
    input_shape = None
    if args.input_shape:
        try:
            input_shape = tuple(int(x.strip()) for x in args.input_shape.split(","))
        except ValueError:
            console.print(
                f"[bold red]Error:[/bold red] Invalid input shape format: {args.input_shape}"
            )
            console.print('[yellow]Expected format: "dim1,dim2,..." (e.g., "1,32,64")[/yellow]')
            return

    # Determine model name
    model_name = args.name
    if model_name is None:
        model_name = os.path.splitext(os.path.basename(args.model_path))[0]

    console.print(f"[bold]Deploying model:[/bold] {model_name}")
    console.print(f"[bold]Source:[/bold] {args.model_path}")
    console.print(f"[bold]Target:[/bold] {args.uri}:{DEVICE_MODEL_DIR}/{model_name}.dlc")
    console.print()

    # Step 1: Convert model to DLC
    console.print("[bold cyan]Converting model to DLC format...[/bold cyan]")

    dlc_path = convert_to_dlc(
        args.model_path,
        input_shape=input_shape,
        console=console,
    )

    if dlc_path is None:
        console.print("[bold red]Model conversion failed[/bold red]")
        return

    console.print()

    # Step 2: Connect to device via SFTP
    console.print("[bold cyan]Connecting to device...[/bold cyan]")

    connections = _setup_connection(
        args.uri,
        args.username,
        args.env_file,
        args.forget_password,
        console,
    )

    if connections is None:
        return

    ssh, sftp_conn = connections

    try:
        # Step 3: Ensure model directory exists
        _ensure_model_dir(sftp_conn, console)

        # Step 4: Upload the DLC file
        remote_path = f"{DEVICE_MODEL_DIR}/{model_name}.dlc"
        _upload_file(sftp_conn, dlc_path, remote_path, console)

        console.print()
        console.print("[bold green]Model deployed successfully![/bold green]")
        console.print()
        console.print("[dim]To use in your app:[/dim]")
        console.print(f'[cyan]  auto model = synapse::Model::load("{model_name}");[/cyan]')

    finally:
        sftp.close_sftp(ssh, sftp_conn)


def _setup_connection(
    uri: str,
    username: str,
    env_file: str,
    forget_password: bool,
    console: Console,
) -> Optional[tuple]:
    """Set up SFTP connection to device."""
    hostname = uri.split(":")[0] if ":" in uri else uri
    password = find_password(hostname, env_file)

    if password is None:
        console.print(f"[bold red]Didn't find any password for {hostname}[/bold red]")
        return None

    console.print(f"[dim]Connecting to {hostname}:22 as {username}...[/dim]")

    try:
        ssh, sftp_conn = sftp.connect_sftp(hostname, username, password)
    except paramiko.ssh_exception.AuthenticationException:
        console.print(f"[bold red]Authentication failed for {hostname}[/bold red]")
        console.print("[yellow]Incorrect username or password.[/yellow]")
        return None
    except paramiko.ssh_exception.SSHException as e:
        console.print(f"[bold red]SSH connection failed: {e}[/bold red]")
        return None
    except Exception as e:
        console.print(f"[bold red]Connection failed: {e}[/bold red]")
        return None

    if ssh is None or sftp_conn is None:
        console.print(f"[bold red]Failed to connect to {hostname}[/bold red]")
        return None

    if not forget_password:
        save_password(password, env_file, hostname)

    console.print(f"[green]Connected to {hostname}[/green]")
    return ssh, sftp_conn


def _ensure_model_dir(sftp_conn, console: Console):
    """Ensure the model directory exists on the device."""
    try:
        sftp_conn.stat(DEVICE_MODEL_DIR)
    except FileNotFoundError:
        console.print(f"[blue]Creating model directory: {DEVICE_MODEL_DIR}[/blue]")
        try:
            sftp_conn.mkdir(DEVICE_MODEL_DIR)
        except Exception as e:
            console.print(
                f"[yellow]Warning: Could not create model directory: {e}[/yellow]"
            )


def _upload_file(sftp_conn, local_path: str, remote_path: str, console: Console):
    """Upload a file to the device with progress display."""
    file_size = os.path.getsize(local_path)

    console.print(f"[blue]Uploading to {remote_path}...[/blue]")

    prog = progress.Progress(
        progress.SpinnerColumn(),
        progress.TextColumn("[progress.description]{task.description}"),
        progress.BarColumn(),
        progress.DownloadColumn(),
        progress.TransferSpeedColumn(),
        progress.TimeElapsedColumn(),
    )

    with prog:
        task = prog.add_task("Uploading model", total=file_size)

        def update_progress(transferred: int, total: int):
            prog.update(task, completed=transferred)

        sftp_conn.put(local_path, remote_path, callback=update_progress)

    console.print(f"[green]Uploaded to {remote_path}[/green]")
