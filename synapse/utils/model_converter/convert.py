"""Main model conversion pipeline."""

import os
import shutil
from typing import Optional

from rich.console import Console

from synapse.utils.model_converter.pt_to_onnx import convert_pt_to_onnx
from synapse.utils.model_converter.onnx_to_dlc import convert_onnx_to_dlc


def convert_to_dlc(
    model_path: str,
    input_shape: Optional[tuple[int, ...]] = None,
    output_path: Optional[str] = None,
    snpe_root: Optional[str] = None,
    console: Optional[Console] = None,
) -> Optional[str]:
    """Convert a model to DLC format for deployment to Synapse devices.

    Handles .pt (PyTorch), .onnx, and .dlc files:
    - .pt  -> ONNX (on host) -> DLC (in Docker)
    - .onnx -> DLC (in Docker)
    - .dlc  -> returns as-is

    Args:
        model_path: Path to the model file (.pt, .onnx, or .dlc)
        input_shape: Input shape for the model (required if model has dynamic dims)
        output_path: Optional output path for the DLC file
        snpe_root: Path to the SNPE/QAIRT SDK
        console: Rich console for output

    Returns:
        Path to the DLC file, or None if conversion failed
    """
    if not os.path.exists(model_path):
        if console:
            console.print(
                f"[bold red]Error:[/bold red] Model file not found: {model_path}"
            )
        return None

    ext = os.path.splitext(model_path)[1].lower()

    if ext == ".dlc":
        if output_path and output_path != model_path:
            shutil.copy2(model_path, output_path)
            return output_path
        return model_path

    if ext == ".pt":
        return _convert_pt_to_dlc(model_path, input_shape, output_path, snpe_root, console)

    if ext == ".onnx":
        return _convert_onnx_to_dlc(model_path, input_shape, output_path, snpe_root, console)

    if console:
        console.print(f"[bold red]Error:[/bold red] Unsupported file type: {ext}")
        console.print("[yellow]Supported formats: .pt, .onnx, .dlc[/yellow]")
    return None


def _convert_pt_to_dlc(
    pt_path: str,
    input_shape: Optional[tuple[int, ...]],
    output_path: Optional[str],
    snpe_root: Optional[str],
    console: Optional[Console],
) -> Optional[str]:
    """Convert PyTorch model to DLC via ONNX."""
    if console:
        console.print("[bold blue]Step 1/2:[/bold blue] Converting PyTorch to ONNX...")

    onnx_path = convert_pt_to_onnx(
        pt_path,
        output_path=None,
        input_shape=input_shape,
        console=console,
    )

    if onnx_path is None:
        return None

    if console:
        console.print(
            "[bold blue]Step 2/2:[/bold blue] Converting ONNX to DLC (Docker)..."
        )

    return convert_onnx_to_dlc(
        onnx_path,
        output_path=output_path,
        input_shape=input_shape,
        snpe_root=snpe_root,
        console=console,
    )


def _convert_onnx_to_dlc(
    onnx_path: str,
    input_shape: Optional[tuple[int, ...]],
    output_path: Optional[str],
    snpe_root: Optional[str],
    console: Optional[Console],
) -> Optional[str]:
    """Convert ONNX model to DLC via Docker."""
    if console:
        console.print("[bold blue]Converting ONNX to DLC (Docker)...[/bold blue]")

    return convert_onnx_to_dlc(
        onnx_path,
        output_path=output_path,
        input_shape=input_shape,
        snpe_root=snpe_root,
        console=console,
    )
