"""ONNX to DLC conversion via Docker container.

The conversion runs inside a Docker container that has Python 3.10 and
the required dependencies pre-installed. The user's SNPE/QAIRT SDK is
bind-mounted at runtime (not baked into the image) to comply with
Qualcomm's license terms.
"""

import os
import shutil
import subprocess
import tempfile
from typing import Optional

from rich.console import Console

DOCKER_IMAGE = "synapse-model-converter:latest"


def _find_model_converter_dir() -> str:
    """Locate the model-converter/ directory containing the Dockerfile."""
    # Walk up from this file to the repo root
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    candidate = os.path.join(repo_root, "model-converter")
    if os.path.isdir(candidate) and os.path.isfile(
        os.path.join(candidate, "Dockerfile")
    ):
        return candidate
    raise FileNotFoundError(
        f"model-converter/ directory not found at {candidate}. "
        "Make sure you are running from the synapse-python repository."
    )


def _image_exists() -> bool:
    """Check if the Docker image is already built."""
    result = subprocess.run(
        ["docker", "image", "inspect", DOCKER_IMAGE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _build_image(console: Optional[Console] = None) -> bool:
    """Build the model-converter Docker image."""
    try:
        build_dir = _find_model_converter_dir()
    except FileNotFoundError as e:
        if console:
            console.print(f"[bold red]Error:[/bold red] {e}")
        return False

    if console:
        console.print(
            f"[yellow]Building Docker image [bold]{DOCKER_IMAGE}[/bold] "
            f"(first time only)...[/yellow]"
        )

    try:
        subprocess.run(
            ["docker", "build", "-t", DOCKER_IMAGE, "."],
            cwd=build_dir,
            check=True,
        )
    except subprocess.CalledProcessError:
        if console:
            console.print(
                "[bold red]Error:[/bold red] Failed to build model-converter Docker image"
            )
        return False

    if console:
        console.print(f"[green]Docker image {DOCKER_IMAGE} built successfully[/green]")
    return True


def ensure_docker(console: Optional[Console] = None) -> bool:
    """Check that Docker is available and the image is built."""
    if shutil.which("docker") is None:
        if console:
            console.print(
                "[bold red]Error:[/bold red] Docker is required for model conversion "
                "but was not found. Please install Docker."
            )
        return False

    try:
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except subprocess.CalledProcessError:
        if console:
            console.print(
                "[bold red]Error:[/bold red] Docker daemon is not running. "
                "Please start Docker and try again."
            )
        return False

    if not _image_exists():
        return _build_image(console)

    return True


def convert_onnx_to_dlc(
    onnx_path: str,
    output_path: Optional[str] = None,
    input_shape: Optional[tuple[int, ...]] = None,
    input_name: str = "input",
    snpe_root: Optional[str] = None,
    console: Optional[Console] = None,
) -> Optional[str]:
    """Convert an ONNX model to DLC format using the Docker-based converter.

    Args:
        onnx_path: Path to the ONNX model
        output_path: Optional output path for the DLC file
        input_shape: Input shape (required if model has dynamic dims)
        input_name: Name of the input tensor
        snpe_root: Path to the SNPE/QAIRT SDK
        console: Rich console for output

    Returns:
        Path to the converted DLC file, or None on failure
    """
    if snpe_root is None:
        snpe_root = os.environ.get("SNPE_ROOT") or os.environ.get("QAIRT_ROOT")

    if snpe_root is None:
        if console:
            console.print(
                "[bold red]Error:[/bold red] --snpe-root is required "
                "(or set SNPE_ROOT / QAIRT_ROOT env var)"
            )
        return None

    snpe_root = os.path.abspath(snpe_root)
    if not os.path.isdir(snpe_root):
        if console:
            console.print(
                f"[bold red]Error:[/bold red] SNPE root not found: {snpe_root}"
            )
        return None

    if not ensure_docker(console):
        return None

    # Resolve paths for Docker mounts
    onnx_path = os.path.abspath(onnx_path)
    onnx_dir = os.path.dirname(onnx_path)
    onnx_filename = os.path.basename(onnx_path)

    if output_path is None:
        base_name = os.path.splitext(onnx_filename)[0]
        output_path = os.path.join(tempfile.gettempdir(), f"{base_name}.dlc")

    output_dir = os.path.abspath(os.path.dirname(output_path))
    output_filename = os.path.basename(output_path)
    os.makedirs(output_dir, exist_ok=True)

    # Build docker run command
    # Run as the host user so output files have correct ownership
    cmd = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-v",
        f"{onnx_dir}:/input:ro",
        "-v",
        f"{snpe_root}:/snpe:ro",
        "-v",
        f"{output_dir}:/output",
        DOCKER_IMAGE,
        "--input",
        f"/input/{onnx_filename}",
        "--output",
        f"/output/{output_filename}",
        "--snpe-root",
        "/snpe",
    ]

    if input_shape is not None:
        shape_str = ",".join(str(d) for d in input_shape)
        cmd.extend(["--input-shape", shape_str])

    if input_name != "input":
        cmd.extend(["--input-name", input_name])

    if console:
        console.print("[dim]Running conversion in Docker container...[/dim]")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        if console:
            console.print(
                "[bold red]Error:[/bold red] Conversion timed out after 10 minutes"
            )
        return None

    # Display container output
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                if console:
                    console.print(f"  {line}")

    if result.returncode != 0:
        if console:
            console.print("[bold red]DLC conversion failed:[/bold red]")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-15:]:
                    if line.strip():
                        console.print(f"[red]  {line}[/red]")
        return None

    if not os.path.exists(output_path):
        if console:
            console.print(
                "[bold red]Error:[/bold red] Container exited OK but DLC file not found"
            )
        return None

    if console:
        console.print(f"[green]Successfully converted to {output_path}[/green]")

    return output_path
