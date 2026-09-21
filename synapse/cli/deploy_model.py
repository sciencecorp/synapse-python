"""CLI command for deploying models to Synapse devices."""

import argparse

import grpc
import os
from typing import Optional

from rich.console import Console
from rich import progress
from rich.prompt import Confirm

from synapse import Device
from synapse.client import files as files_client

# Constants
DEVICE_MODEL_DIR = "models"


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
        help="Model name on device (default: filename without extension, e.g., 'my_model')",
    )

    # Retired with SFTP. Kept parseable so an existing script gets an
    # explanation rather than an unknown-argument error.
    parser.add_argument("--username", type=str, default=None, help=argparse.SUPPRESS)

    parser.add_argument("--env-file", "-e", type=str, default=None, help=argparse.SUPPRESS)

    parser.add_argument("--forget-password", "-f", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument(
        "--snpe-root",
        type=str,
        default=None,
        help="Path to SNPE/QAIRT SDK root (or set SNPE_ROOT env var)",
    )

    parser.add_argument(
        "--quantize",
        action="store_true",
        help=(
            "Quantize the model to INT8 for DSP inference. Requires --input-list with "
            "representative input samples. Quantized models run on the HTP/DSP backend "
            "for maximum performance (~1ms). Without quantization, models run on CPU."
        ),
    )

    parser.add_argument(
        "--input-list",
        type=str,
        default=None,
        help=(
            "Path to a text file listing representative input samples for INT8 quantization. "
            "Each line is a path to a .raw file (float32 binary). Required with --quantize. "
            "Generate .raw files with: arr.astype(np.float32).tofile('sample.raw')"
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing model on device without prompting",
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

    # Default dynamic dimensions to 1 if the model has them and no --input-shape given
    if input_shape is None:
        ext = os.path.splitext(args.model_path)[1].lower()
        if ext == ".onnx":
            try:
                import onnx

                onnx_model = onnx.load(args.model_path)
                for inp in onnx_model.graph.input:
                    dims = inp.type.tensor_type.shape.dim
                    has_dynamic = any(d.dim_param or d.dim_value == 0 for d in dims)
                    if has_dynamic:
                        resolved = []
                        for d in dims:
                            if d.dim_param or d.dim_value == 0:
                                resolved.append(1)
                            else:
                                resolved.append(d.dim_value)
                        input_shape = tuple(resolved)
                        console.print(
                            f"[yellow]Note: model has dynamic dimensions, "
                            f"defaulting to {input_shape}[/yellow]"
                        )
                        break
            except Exception:
                pass  # If onnx isn't installed or can't load, let the converter handle it

    # Default model name to filename without extension
    model_name = args.name
    if model_name is None:
        model_name = os.path.splitext(os.path.basename(args.model_path))[0]
    quantize = args.quantize

    # Validate quantize + input-list
    if quantize and not args.input_list:
        console.print(
            "[bold red]Error:[/bold red] --quantize requires --input-list "
            "with representative input samples for INT8 calibration."
        )
        console.print()
        console.print("[dim]Example:[/dim]")
        console.print("  synapsectl deploy-model model.onnx --name my_model \\")
        console.print("    --quantize --input-list calibration_data.txt \\")
        console.print("    --snpe-root /path/to/qairt/2.34.0.250424 -u <device>")
        return

    if quantize:
        fmt_str = "Quantized DLC (INT8) — runs on DSP"
    else:
        fmt_str = "ONNX (float32) — runs on CPU via ONNX Runtime"

    console.print(f"[bold]Deploying model:[/bold] {model_name}")
    console.print(f"[bold]Source:[/bold] {args.model_path}")
    console.print(f"[bold]Format:[/bold] {fmt_str}")
    console.print()

    # Step 1: Prepare model for deployment
    if quantize:
        # Quantized path: convert to DLC via Docker (requires QAIRT SDK)
        console.print("[bold cyan]Converting model to quantized DLC...[/bold cyan]")

        from synapse.utils.model_converter import convert_to_dlc

        dlc_path = convert_to_dlc(
            args.model_path,
            input_shape=input_shape,
            snpe_root=args.snpe_root,
            quantize=quantize,
            input_list=args.input_list,
            console=console,
        )

        if dlc_path is None:
            console.print("[bold red]Model conversion failed[/bold red]")
            return

        deploy_path = dlc_path
        remote_ext = ".dlc"
    else:
        # Non-quantized path: deploy .onnx directly (no QAIRT SDK needed)
        ext = os.path.splitext(args.model_path)[1].lower()

        if ext == ".dlc":
            deploy_path = args.model_path
            remote_ext = ".dlc"
        elif ext == ".pt":
            console.print("[bold cyan]Converting PyTorch model to ONNX...[/bold cyan]")
            from synapse.utils.model_converter.pt_to_onnx import convert_pt_to_onnx

            onnx_path = convert_pt_to_onnx(
                args.model_path,
                input_shape=input_shape,
                console=console,
            )
            if onnx_path is None:
                console.print("[bold red]Model conversion failed[/bold red]")
                return

            deploy_path = onnx_path
            remote_ext = ".onnx"
        elif ext == ".onnx":
            deploy_path = args.model_path
            remote_ext = ".onnx"
        else:
            console.print(f"[bold red]Error:[/bold red] Unsupported file type: {ext}")
            console.print("[yellow]Supported formats: .pt, .onnx, .dlc[/yellow]")
            return

    console.print()

    # Step 2: Connect to the device. No SFTP password: the pairing token that
    # governs every other RPC governs this too.
    console.print("[bold cyan]Connecting to device...[/bold cyan]")
    device = Device(args.uri, getattr(args, "verbose", False))

    try:
        # Step 3: No mkdir. WriteFile creates parent directories for whatever
        # path the stream names, so models/ appears when the model lands.

        # Step 4: Check if the model already exists. This is only the overwrite
        # prompt -- ListFiles rather than a stat, since that is the RPC that
        # reports existence.
        remote_path = f"{DEVICE_MODEL_DIR}/{model_name}{remote_ext}"
        try:
            existing = {f.path for f in files_client.list_files(device, DEVICE_MODEL_DIR)}
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.UNAUTHENTICATED:
                console.print(
                    "[bold red]Not paired with this device.[/bold red] Run "
                    "[bold]synapsectl pair[/bold] first."
                )
                return
            # Any other failure here (a missing models dir, for instance) just
            # means we cannot pre-check; the upload itself will still report.
            existing = set()

        if remote_path in existing and not args.force:
            if not Confirm.ask(
                f"[yellow]Model '{model_name}{remote_ext}' already exists on device. Overwrite?[/yellow]",
                default=False,
            ):
                console.print("[dim]Aborted.[/dim]")
                return

        # Step 5: Upload the model file
        _upload_file(device, deploy_path, remote_path, console)

        console.print()
        console.print("[bold green]Model deployed successfully![/bold green]")
        console.print()
        console.print(f"  Model deployed: [cyan]models/{model_name}{remote_ext}[/cyan]")
        if quantize:
            console.print(f"  Runtime: [cyan]DSP (quantized INT8)[/cyan]")
        else:
            console.print(f"  Runtime: [cyan]CPU (float32, ONNX Runtime)[/cyan]")
            console.print()
            console.print(
                "  [dim]Tip: for faster DSP inference (~1ms), redeploy with --quantize --input-list[/dim]"
            )
        console.print()
        console.print("  To load in your app:")
        console.print(f'    [cyan]auto model = synapse::create_model("{model_name}");[/cyan]')

    finally:
        pass


def _upload_file(device, local_path: str, remote_path: str, console: Console):
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

        files_client.write_file(
            device, local_path, remote_path, progress=update_progress
        )

    console.print(f"[green]Uploaded to {remote_path}[/green]")
