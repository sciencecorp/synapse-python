"""ONNX to DLC conversion using SNPE converter.

Requirements for ONNX→DLC conversion:
- QAIRT SDK (set SNPE_ROOT or QAIRT_ROOT environment variable)
- Python 3.10 with: numpy, onnx, pyyaml, packaging, protobuf
- System libraries: libc++1 (sudo apt install libc++1)
- LD_LIBRARY_PATH must include path to libpython3.10.so
"""

import os
import shutil
import subprocess
import tempfile
from typing import Optional

from rich.console import Console


def _get_snpe_root() -> Optional[str]:
    """Get SNPE/QAIRT SDK root from environment."""
    return os.environ.get("SNPE_ROOT") or os.environ.get("QAIRT_ROOT")


def find_snpe_converter(snpe_root: Optional[str] = None) -> Optional[str]:
    """
    Find the snpe-onnx-to-dlc converter binary.

    Args:
        snpe_root: Optional path to SNPE/QAIRT SDK root

    Returns:
        Path to the converter binary, or None if not found
    """
    if snpe_root is None:
        snpe_root = _get_snpe_root()

    if snpe_root is None:
        return None

    converter_path = os.path.join(
        snpe_root, "bin", "x86_64-linux-clang", "snpe-onnx-to-dlc"
    )

    if os.path.exists(converter_path):
        return converter_path

    return None


def _find_python310() -> Optional[str]:
    """Find Python 3.10 executable."""
    # Check common locations
    candidates = [
        "/usr/bin/python3.10",
        shutil.which("python3.10"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def _setup_converter_env(snpe_root: str) -> dict:
    """
    Set up environment variables for the SNPE converter.

    The converter requires:
    - SNPE_ROOT pointing to SDK
    - PYTHONPATH with SDK's Python libs first, then system packages (for onnx, numpy, etc.)
    - LD_LIBRARY_PATH including libpython3.10.so location
    """
    env = os.environ.copy()

    # Set SNPE_ROOT
    env["SNPE_ROOT"] = snpe_root

    # Set PYTHONPATH - SDK's Python libs must come first, but we also need
    # access to installed packages (onnx, numpy, etc.)
    python_lib_path = os.path.join(snpe_root, "lib", "python")
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{python_lib_path}:{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = python_lib_path

    # Set LD_LIBRARY_PATH for libpython3.10.so
    ld_paths = ["/usr/lib/x86_64-linux-gnu"]
    if "LD_LIBRARY_PATH" in env:
        ld_paths.append(env["LD_LIBRARY_PATH"])
    env["LD_LIBRARY_PATH"] = ":".join(ld_paths)

    return env


def convert_onnx_to_dlc(
    onnx_path: str,
    output_path: Optional[str] = None,
    input_shape: Optional[tuple[int, ...]] = None,
    input_name: str = "input",
    snpe_root: Optional[str] = None,
    console: Optional[Console] = None,
) -> Optional[str]:
    """
    Convert an ONNX model to DLC format using SNPE converter.

    Args:
        onnx_path: Path to the ONNX model
        output_path: Optional output path for the DLC file
        input_shape: Input shape to use (required if model has dynamic dims)
        input_name: Name of the input tensor (default: "input")
        snpe_root: Optional path to SNPE/QAIRT SDK root
        console: Rich console for output

    Returns:
        Path to the converted DLC file, or None if conversion failed
    """
    if snpe_root is None:
        snpe_root = _get_snpe_root()

    if snpe_root is None:
        if console:
            console.print(
                "[bold red]Error:[/bold red] SNPE_ROOT or QAIRT_ROOT environment variable not set"
            )
            console.print(
                "[yellow]Hint: export SNPE_ROOT=/path/to/qairt/x.xx.x.xxxxxx[/yellow]"
            )
        return None

    converter_path = find_snpe_converter(snpe_root)
    if converter_path is None:
        if console:
            console.print(
                "[bold red]Error:[/bold red] Could not find snpe-onnx-to-dlc converter"
            )
            console.print(
                f"[yellow]Expected at: {snpe_root}/bin/x86_64-linux-clang/snpe-onnx-to-dlc[/yellow]"
            )
        return None

    # Determine output path
    if output_path is None:
        base_name = os.path.splitext(os.path.basename(onnx_path))[0]
        output_path = os.path.join(tempfile.gettempdir(), f"{base_name}.dlc")

    if console:
        console.print(f"[blue]Converting ONNX to DLC: {output_path}...[/blue]")

    # Build command - use -d for input dimensions (short form)
    cmd = [
        converter_path,
        "--input_network", onnx_path,
        "--output_path", output_path,
    ]

    # Add input shape if provided
    if input_shape is not None:
        shape_str = ",".join(str(d) for d in input_shape)
        cmd.extend(["-d", input_name, shape_str])

    # Set up environment
    env = _setup_converter_env(snpe_root)

    if console:
        console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode != 0:
            if console:
                console.print("[bold red]DLC conversion failed:[/bold red]")
                if result.stderr:
                    _display_conversion_error(result.stderr, console)
                if result.stdout:
                    console.print(f"[dim]{result.stdout}[/dim]")
            return None

        if not os.path.exists(output_path):
            if console:
                console.print(
                    "[bold red]Error:[/bold red] Converter ran but DLC file was not created"
                )
            return None

        if console:
            console.print(f"[green]Successfully converted to {output_path}[/green]")

        return output_path

    except subprocess.TimeoutExpired:
        if console:
            console.print("[bold red]Error:[/bold red] Conversion timed out after 5 minutes")
        return None
    except Exception as e:
        if console:
            console.print(f"[bold red]Error running converter:[/bold red] {e}")
        return None


def _display_conversion_error(stderr: str, console: Console):
    """Display helpful error messages based on converter output."""
    lines = stderr.strip().split("\n")

    # Common error patterns and suggestions
    error_hints = {
        "unsupported op": (
            "The model contains an unsupported operation. "
            "Try simplifying the model or using a different export configuration."
        ),
        "dynamic": (
            "The model has dynamic shapes. "
            "Provide a fixed input shape with --input-shape."
        ),
        "opset": (
            "The ONNX opset version may be too new. "
            "Try exporting with an older opset version (e.g., opset 11)."
        ),
        "memory": (
            "The conversion ran out of memory. "
            "Try reducing model size or batch dimension."
        ),
    }

    # Display first few error lines
    for line in lines[-10:]:
        if line.strip():
            console.print(f"[red]{line}[/red]")

    # Check for known patterns and provide hints
    stderr_lower = stderr.lower()
    for pattern, hint in error_hints.items():
        if pattern in stderr_lower:
            console.print(f"\n[yellow]Hint: {hint}[/yellow]")
            break
