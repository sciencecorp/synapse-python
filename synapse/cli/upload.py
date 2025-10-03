import os
import subprocess
from rich.console import Console

def upload(args):
    console = Console()

    if not args.filename:
        console.print("[bold red]Error: No filename specified[/bold red]")
        return
    
    if not os.path.exists(args.filename):
        console.print(f"[bold red]Error: File '{args.filename}does not exist[/bold red]")
        return

    file_size = os.path.getsize(args.filename)
    file_size_mb = file_size / (1024 * 1024)

    uri = args.uri
    remote_host = f"scifi@{uri}"
    remote_dir = "~/replay"
    remote_path = f"{remote_host}:{remote_dir}"
    mkdir_command = ["ssh", remote_host, f"mkdir -p {remote_dir}"]
    scp_command = ["scp", args.filename, remote_path]

    console.print(f"[cyan]Uploading file:[/cyan] {args.filename}")
    console.print(f"[cyan]File size:[/cyan] {file_size_mb:.2f} MB")
    console.print(f"[cyan]Destination:[/cyan] {remote_path}")

    try:
        # Ensure ~/replay directory exists
        console.print(f"\n[cyan]Ensuring directory exists: {remote_dir}[/cyan]")
        subprocess.run(mkdir_command, check=True, capture_output=True, text=True)
        console.print(f"[green]✓ Directory ready[/green]")

        # Copy over the file
        console.print(f"\n[cyan]Uploading to {remote_path}...[/cyan]")
        console.print("[dim]You may be prompted for a password[/dim]\n")
        result = subprocess.run(scp_command, check=True)
        console.print(f"\n[bold green]✓ Successfully uploaded {args.filename}[/bold green]")
        
    except subprocess.CalledProcessError as e:
        console.print(f"\n[bold red]✗ Upload failed[/bold red]")

def add_commands(subparsers):
    upload_parser = subparsers.add_parser("upload", help="Upload HDF5 recordings to your Synapse device")
    upload_parser.add_argument("filename", type=str, help="Path to the file to upload")
    upload_parser.set_defaults(func=upload)
