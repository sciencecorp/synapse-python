"""PyTorch to ONNX model conversion."""

import os
import tempfile
from typing import Optional

from rich.console import Console


def convert_pt_to_onnx(
    pt_path: str,
    output_path: Optional[str] = None,
    input_shape: Optional[tuple[int, ...]] = None,
    console: Optional[Console] = None,
) -> Optional[str]:
    """
    Convert a PyTorch model to ONNX format.

    Args:
        pt_path: Path to the .pt file
        output_path: Optional output path for the ONNX file. If None, uses temp directory.
        input_shape: Input shape for the model (required for tracing)
        console: Rich console for output

    Returns:
        Path to the converted ONNX file, or None if conversion failed
    """
    try:
        import torch
    except ImportError:
        if console:
            console.print("[bold red]Error:[/bold red] torch is required for PT to ONNX conversion")
            console.print("[yellow]Install with: pip install torch[/yellow]")
        return None

    if console:
        console.print(f"[blue]Loading PyTorch model from {pt_path}...[/blue]")

    try:
        model = torch.load(pt_path, map_location="cpu", weights_only=False)
    except Exception as e:
        if console:
            console.print(f"[bold red]Failed to load PyTorch model:[/bold red] {e}")
        return None

    # Handle case where saved file is a state_dict instead of a full model
    if isinstance(model, dict):
        if console:
            console.print(
                "[bold red]Error:[/bold red] The .pt file contains a state_dict, not a full model."
            )
            console.print(
                "[yellow]Hint: Save the model with torch.save(model, path) instead of "
                "torch.save(model.state_dict(), path)[/yellow]"
            )
        return None

    model.eval()

    # Determine input shape
    if input_shape is None:
        # Try to infer input shape from the model
        input_shape = _infer_input_shape(model)
        if input_shape is None:
            if console:
                console.print(
                    "[bold red]Error:[/bold red] Could not infer input shape. "
                    "Please provide --input-shape"
                )
            return None
        if console:
            console.print(f"[green]Inferred input shape: {input_shape}[/green]")

    # Create dummy input
    dummy_input = torch.randn(*input_shape)

    # Determine output path
    if output_path is None:
        base_name = os.path.splitext(os.path.basename(pt_path))[0]
        output_path = os.path.join(tempfile.gettempdir(), f"{base_name}.onnx")

    if console:
        console.print(f"[blue]Exporting to ONNX: {output_path}...[/blue]")

    try:
        torch.onnx.export(
            model,
            dummy_input,
            output_path,
            export_params=True,
            opset_version=13,
            do_constant_folding=True,
            input_names=["input"],
            output_names=["output"],
            dynamic_axes=None,  # Static shapes for device deployment
        )
    except Exception as e:
        if console:
            console.print(f"[bold red]ONNX export failed:[/bold red] {e}")
        return None

    if console:
        console.print(f"[green]Successfully exported to {output_path}[/green]")

    return output_path


def _infer_input_shape(model) -> Optional[tuple[int, ...]]:
    """
    Try to infer input shape from model structure.

    Returns:
        Inferred input shape tuple, or None if cannot be inferred
    """
    try:
        import torch.nn as nn

        # Check if it's a Sequential model with a first Linear layer
        if isinstance(model, nn.Sequential):
            first_layer = list(model.children())[0]
            if isinstance(first_layer, nn.Linear):
                return (1, first_layer.in_features)

        # Check for common first layer patterns
        for name, module in model.named_modules():
            if isinstance(module, nn.Linear) and "." not in name:
                return (1, module.in_features)
            if isinstance(module, nn.Conv1d) and "." not in name:
                # For Conv1d, we need channels and sequence length
                # Use a reasonable default sequence length
                return (1, module.in_channels, 64)
            if isinstance(module, nn.Conv2d) and "." not in name:
                # For Conv2d, use a reasonable default spatial size
                return (1, module.in_channels, 32, 32)

    except Exception:
        pass

    return None
