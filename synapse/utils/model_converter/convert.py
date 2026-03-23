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
    quantize: bool = False,
    input_list: Optional[str] = None,
    compile_context: bool = False,
    console: Optional[Console] = None,
) -> Optional[str]:
    """Convert a model for deployment to Synapse devices.

    Handles .pt (PyTorch), .onnx, and .dlc files:
    - .pt  -> ONNX (on host) -> DLC or .bin (in Docker)
    - .onnx -> DLC or .bin (in Docker)
    - .dlc  -> returns as-is

    When compile_context=True, produces a QNN context binary (.bin) that is
    pre-compiled for the HTP backend, enabling DSP inference.

    Args:
        model_path: Path to the model file (.pt, .onnx, or .dlc)
        input_shape: Input shape for the model (required if model has dynamic dims)
        output_path: Optional output path
        snpe_root: Path to the QAIRT SDK
        quantize: Whether to quantize the model to INT8
        input_list: Path to representative input list file (required if quantize=True)
        compile_context: Whether to compile a QNN context binary for HTP
        console: Rich console for output

    Returns:
        Path to the output file, or None if conversion failed
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

    kwargs = dict(
        input_shape=input_shape,
        output_path=output_path,
        snpe_root=snpe_root,
        quantize=quantize,
        input_list=input_list,
        compile_context=compile_context,
        console=console,
    )

    if ext == ".pt":
        if console:
            console.print("[bold blue]Step 1/2:[/bold blue] Converting PyTorch to ONNX...")

        onnx_path = convert_pt_to_onnx(
            model_path, output_path=None, input_shape=input_shape, console=console,
        )
        if onnx_path is None:
            return None

        if console:
            console.print("[bold blue]Step 2/2:[/bold blue] Converting ONNX (Docker)...")

        return convert_onnx_to_dlc(onnx_path, **kwargs)

    if ext == ".onnx":
        if console:
            console.print("[bold blue]Converting ONNX (Docker)...[/bold blue]")
        return convert_onnx_to_dlc(model_path, **kwargs)

    if console:
        console.print(f"[bold red]Error:[/bold red] Unsupported file type: {ext}")
        console.print("[yellow]Supported formats: .pt, .onnx, .dlc[/yellow]")
    return None
