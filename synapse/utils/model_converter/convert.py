"""Main model conversion pipeline."""

import os
import shutil
import tempfile
from typing import Optional

from rich.console import Console

from synapse.utils.model_converter.pt_to_onnx import convert_pt_to_onnx
from synapse.utils.model_converter.onnx_transforms import (
    apply_transforms,
    has_dynamic_shapes,
    get_input_shapes,
)
from synapse.utils.model_converter.onnx_to_dlc import convert_onnx_to_dlc


def convert_to_dlc(
    model_path: str,
    input_shape: Optional[tuple[int, ...]] = None,
    output_path: Optional[str] = None,
    console: Optional[Console] = None,
) -> Optional[str]:
    """
    Convert a model to DLC format for deployment to Synapse devices.

    Handles .pt (PyTorch), .onnx, and .dlc files:
    - .pt → ONNX → DLC
    - .onnx → DLC
    - .dlc → returns as-is

    Args:
        model_path: Path to the model file (.pt, .onnx, or .dlc)
        input_shape: Input shape for the model (required if model has dynamic dims)
        output_path: Optional output path for the DLC file
        console: Rich console for output

    Returns:
        Path to the DLC file, or None if conversion failed
    """
    if not os.path.exists(model_path):
        if console:
            console.print(f"[bold red]Error:[/bold red] Model file not found: {model_path}")
        return None

    ext = os.path.splitext(model_path)[1].lower()

    if ext == ".dlc":
        # Already a DLC, just return or copy
        if output_path and output_path != model_path:
            shutil.copy2(model_path, output_path)
            return output_path
        return model_path

    if ext == ".pt":
        return _convert_pt_to_dlc(model_path, input_shape, output_path, console)

    if ext == ".onnx":
        return _convert_onnx_to_dlc(model_path, input_shape, output_path, console)

    if console:
        console.print(
            f"[bold red]Error:[/bold red] Unsupported file type: {ext}"
        )
        console.print("[yellow]Supported formats: .pt, .onnx, .dlc[/yellow]")
    return None


def _convert_pt_to_dlc(
    pt_path: str,
    input_shape: Optional[tuple[int, ...]],
    output_path: Optional[str],
    console: Optional[Console],
) -> Optional[str]:
    """Convert PyTorch model to DLC via ONNX."""
    if console:
        console.print("[bold blue]Step 1/3:[/bold blue] Converting PyTorch to ONNX...")

    # Create temp ONNX file
    onnx_path = convert_pt_to_onnx(
        pt_path,
        output_path=None,  # Use temp directory
        input_shape=input_shape,
        console=console,
    )

    if onnx_path is None:
        return None

    return _convert_onnx_to_dlc(onnx_path, input_shape, output_path, console, step_offset=1)


def _convert_onnx_to_dlc(
    onnx_path: str,
    input_shape: Optional[tuple[int, ...]],
    output_path: Optional[str],
    console: Optional[Console],
    step_offset: int = 0,
) -> Optional[str]:
    """Convert ONNX model to DLC."""
    step1 = step_offset + 1
    step2 = step_offset + 2

    # Check for dynamic shapes
    if has_dynamic_shapes(onnx_path):
        if input_shape is None:
            if console:
                shapes = get_input_shapes(onnx_path)
                console.print(
                    "[bold red]Error:[/bold red] Model has dynamic input shapes."
                )
                console.print("[yellow]Current input shapes:[/yellow]")
                for name, shape in shapes:
                    console.print(f"  {name}: {shape}")
                console.print(
                    "\n[yellow]Please provide --input-shape with concrete dimensions.[/yellow]"
                )
            return None
        if console:
            console.print(
                f"[yellow]Note: Using provided input shape {input_shape} for dynamic model[/yellow]"
            )

    if console:
        console.print(f"[bold blue]Step {step1}/{step2 + 1}:[/bold blue] Applying ONNX transformations...")

    # Apply transforms to a temp copy to avoid modifying the original
    temp_dir = tempfile.mkdtemp()
    temp_onnx = os.path.join(temp_dir, os.path.basename(onnx_path))
    shutil.copy2(onnx_path, temp_onnx)

    try:
        apply_transforms(temp_onnx, console=console)
    except Exception as e:
        if console:
            console.print(
                f"[yellow]Warning: Could not apply transforms: {e}. "
                "Proceeding with original model.[/yellow]"
            )
        temp_onnx = onnx_path

    if console:
        console.print(f"[bold blue]Step {step2}/{step2 + 1}:[/bold blue] Converting to DLC...")

    # Determine input name from ONNX model
    input_name = "input"
    try:
        shapes = get_input_shapes(temp_onnx)
        if shapes:
            input_name = shapes[0][0]
    except Exception:
        pass

    dlc_path = convert_onnx_to_dlc(
        temp_onnx,
        output_path=output_path,
        input_shape=input_shape,
        input_name=input_name,
        console=console,
    )

    # Cleanup temp files
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass

    return dlc_path
