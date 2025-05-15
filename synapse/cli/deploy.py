import hashlib
import os

from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text
from rich.live import Live
from rich.console import Group

from synapse.cli import build as builder
import synapse as syn
from synapse.api.app_pb2 import PackageMetadata, AppPackageChunk

# 1MB chunks
FILE_CHUNK_SIZE = 1024 * 1024


console = Console()
log_console = Console(stderr=True)


def calculate_sha256(file_path):
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()

    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)

    return sha256_hash.hexdigest()


def extract_version(package_name):
    """Extract version from debian package name."""
    try:
        # Format: package-name_version_architecture.deb
        parts = package_name.split("_")
        if len(parts) >= 2:
            return parts[1]
    except Exception:
        pass

    return ""


def create_metadata(file_path, console):
    """Create package metadata from file."""
    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    with console.status(
        f"[bold blue]Calculating SHA256 for [cyan]{file_name}[/cyan]...", spinner="dots"
    ):
        sha256_sum = calculate_sha256(file_path)

    version = extract_version(file_name)

    metadata = PackageMetadata(
        name=file_name, version=version, size=file_size, sha256_sum=sha256_sum
    )

    meta_text = Text()
    meta_text.append("Package Metadata\n", style="bold blue")
    meta_text.append(f"Name: {metadata.name}\n", style="cyan")
    meta_text.append(f"Version: {metadata.version}\n", style="cyan")
    meta_text.append(f"Size: {metadata.size:,} bytes\n", style="cyan")
    meta_text.append(f"SHA256: {metadata.sha256_sum}", style="cyan")
    console.print(Panel(meta_text, border_style="blue"))

    return metadata


def deploy_package(ip_address, deb_package_path):
    """Deploy the package to the device"""
    package_filename = os.path.basename(deb_package_path)
    console.clear_live()

    device = syn.Device(ip_address, False)
    metadata = create_metadata(deb_package_path, console)
    console.print(
        f"[bold green]Deploying:[/bold green] [cyan]{package_filename}[/cyan]"
    )

    # Load our file into chunks
    chunks = []
    chunk_sizes = []
    total_bytes = 0

    # First chunk is metadata
    chunks.append(AppPackageChunk(metadata=metadata))
    chunk_sizes.append(metadata.size)
    total_bytes += metadata.size

    with console.status("[bold yellow]Loading file...[/bold yellow]", spinner="dots"):
        with open(deb_package_path, "rb") as f:
            chunk_data = f.read(FILE_CHUNK_SIZE)
            while chunk_data:
                chunks.append(AppPackageChunk(file_chunk=chunk_data))
                chunk_size = len(chunk_data)
                chunk_sizes.append(chunk_size)
                total_bytes += chunk_size
                chunk_data = f.read(FILE_CHUNK_SIZE)

    responses = []
    response_panel = Panel("Waiting for responses...", title="Device Responses")
    with Live(response_panel, refresh_per_second=10, console=console) as live:
        try:

            def chunk_generator():
                bytes_sent = 0
                for i, chunk in enumerate(chunks):
                    bytes_sent += chunk_sizes[i]
                    yield chunk

            try:
                device_responses = device.rpc.DeployApp(chunk_generator())
                current_index = 0

                # Process each response from the device
                for response in device_responses:
                    message = str(response.message)

                    # Add this response to our list
                    responses.append(message)

                    # Create a display for all responses
                    display_items = []

                    for i, resp in enumerate(responses):
                        if i < current_index:
                            # Completed response gets a checkmark
                            display_items.append(
                                f"[green]✓[/green] Step {i + 1}: {resp}"
                            )
                        elif i == current_index:
                            # Current response gets a spinner
                            spinner = Spinner("dots", text=f" Step {i + 1}: {resp}")
                            display_items.append(spinner)
                        else:
                            # Future responses (shouldn't happen in this loop, but included for completeness)
                            display_items.append(f"⋯ Step {i + 1}: {resp}")

                    # Update the panel with all responses
                    response_panel.renderable = Group(*display_items)
                    live.refresh()

                    # Move to next response
                    current_index += 1

                if responses:
                    # Create final display with all responses marked complete
                    final_items = [
                        f"[green]✓[/green] Step {i + 1}: {resp}"
                        for i, resp in enumerate(responses)
                    ]
                    response_panel.renderable = Group(*final_items)
                    live.refresh()

            except Exception as e:
                # Instead of replacing the panel, preserve progress and add error
                display_items = []

                # Show completed steps with checkmarks
                for i, resp in enumerate(responses):
                    if i < current_index:
                        display_items.append(f"[green]✓[/green] Step {i + 1}: {resp}")
                    elif i == current_index:
                        # Mark the current step as failed
                        display_items.append(
                            f"[red]✗[/red] Step {i + 1}: {resp} - FAILED"
                        )
                        break

                # Add the error message at the bottom
                display_items.append(f"[bold red]Error: {str(e)}[/bold red]")

                # Update the panel with progress and error
                response_panel.renderable = Group(*display_items)
                response_panel.border_style = "red"
                live.refresh()

        except Exception as e:
            # For the outer exception, also preserve any progress made
            display_items = []

            # Show any completed steps with checkmarks
            for i, resp in enumerate(responses):
                if i < current_index:
                    display_items.append(f"[green]✓[/green] Step {i + 1}: {resp}")

            # Add the error message
            display_items.append(f"[bold red]Error during setup: {str(e)}[/bold red]")

            # Update the panel with progress and error
            response_panel.renderable = Group(*display_items)
            response_panel.border_style = "red"
            live.refresh()


def deploy_cmd(args):
    """Handle the deploy command"""
    # Make sure we have docker, if not it will print an error
    if not builder.ensure_docker():
        return

    # If user supplied a pre-built package, skip local build/pkg steps.
    if args.package:
        deb_package = os.path.abspath(args.package)
        if not os.path.exists(deb_package):
            console.print(
                f"[bold red]Error:[/bold red] Provided package not found: {deb_package}"
            )
            return

        console.print(
            f"[bold]Deploying pre-built package:[/bold] [yellow]{os.path.basename(deb_package)}[/yellow]"
        )

    else:
        # Ensure Docker is available and running only when we need to build
        if not builder.ensure_docker():
            return

        # Get absolute path of app directory
        app_dir = os.path.abspath(args.app_dir)

        # Validate manifest.json
        manifest_path = os.path.join(app_dir, "manifest.json")
        manifest = builder.validate_manifest(manifest_path)
        if not manifest:
            return

        # Get app name from manifest
        app_name = manifest["name"]
        console.print(
            f"[bold]Deploying application:[/bold] [yellow]{app_name}[/yellow]"
        )

        # Build & package locally
        if not builder.build_app(app_dir, app_name):
            console.print(
                "[bold red]Error:[/bold red] Failed to build the application."
            )
            return

        if not builder.package_app(app_dir, app_name):
            return

        deb_package = builder.find_deb_package(app_dir)
        if not deb_package:
            return

    # Deploy the package to the device
    uri = args.uri
    if uri:
        deploy_package(uri, deb_package)
    else:
        console.print(
            "[yellow]No URI provided. Package created but not deployed.[/yellow]"
        )
        console.print(f"[green]Package available at:[/green] {deb_package}")


def add_commands(subparsers):
    """Add deploy commands to the CLI"""
    deploy_parser = subparsers.add_parser(
        "deploy", help="Deploy an application to a Synapse device"
    )
    deploy_parser.add_argument(
        "app_dir", nargs="?", default=".", help="Path to the application directory"
    )
    deploy_parser.add_argument(
        "--package",
        "-p",
        help="Path to a pre-built .deb to deploy (skips local build and package steps)",
        type=str,
        default=None,
    )
    deploy_parser.set_defaults(func=deploy_cmd)
