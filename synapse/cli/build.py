from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel

console = Console()


def validate_manifest(manifest_path: str) -> dict[str, Any] | bool:
    """Return the parsed ``manifest.json`` dictionary or ``False`` on error."""

    try:
        with open(manifest_path, "r", encoding="utf-8") as fp:
            manifest = json.load(fp)

        if "name" not in manifest:
            console.print(
                "[bold red]Error:[/bold red] manifest.json is missing required 'name' property"
            )
            return False
        return manifest
    except FileNotFoundError:
        console.print(
            f"[bold red]Error:[/bold red] manifest.json not found in {manifest_path}"
        )
        return False
    except json.JSONDecodeError:
        console.print("[bold red]Error:[/bold red] manifest.json is not valid JSON")
        return False


def detect_arch() -> str:
    """Return an architecture tag suffix (``arm64`` or ``amd64``)."""
    arch = subprocess.check_output(["uname", "-m"]).decode("utf-8").strip()
    return "arm64" if arch in ("arm64", "aarch64") else "amd64"


def ensure_docker() -> bool:
    """Check that *docker* CLI and daemon are available.

    Prints user-friendly errors and returns ``False`` if Docker cannot be used –
    allowing the caller to abort early without raising.
    """
    if shutil.which("docker") is None:
        console.print(
            "[bold red]Error:[/bold red] Docker CLI not found. Please install Docker before running this command."
        )
        return False

    try:
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        console.print(
            "[bold red]Error:[/bold red] Docker daemon does not appear to be running. Please start Docker and try again."
        )
        return False


def build_docker_image(app_dir: str, app_name: str | None = None) -> str:
    """(Re)build the cross-compile SDK Docker image and return its tag."""

    if app_name is None:
        app_name = os.path.basename(app_dir)

    arch_suffix = detect_arch()  # "arm64" or "amd64"

    # Prefer an arch-specific Dockerfile if provided (``ops/docker/Dockerfile.arm64``)
    dockerfile_rel = (
        f"ops/docker/Dockerfile.{arch_suffix}"
        if arch_suffix == "arm64"
        else "ops/docker/Dockerfile"
    )
    dockerfile_path = os.path.join(app_dir, dockerfile_rel)

    if not os.path.exists(dockerfile_path):
        # Fall back to generic Dockerfile regardless of arch.
        dockerfile_path = os.path.join(app_dir, "ops/docker/Dockerfile")

    if not os.path.exists(dockerfile_path):
        raise FileNotFoundError(
            f"Expected Dockerfile not found at {dockerfile_path}. "
            "Ensure your application provides the required build Dockerfile(s)."
        )

    image_tag = f"{app_name}:latest-{arch_suffix}"

    console.print(f"[yellow]Building Docker image [bold]{image_tag}[/bold]...[/yellow]")
    subprocess.run(
        [
            "docker",
            "build",
            "-t",
            image_tag,
            "-f",
            dockerfile_path,
            ".",
        ],
        check=True,
        cwd=app_dir,
    )

    console.print(f"[green]Successfully built Docker image {image_tag}[/green]")
    return image_tag


def build_app(app_dir: str, app_name: str, force_rebuild: bool = False) -> bool:
    """Cross-compile *app_name* inside its SDK container."""

    console.print(f"[yellow]Building application: {app_name}...[/yellow]")

    binary_path = os.path.join(app_dir, "build-aarch64", app_name)

    # Skip if binary already exists unless a rebuild was requested
    if (not force_rebuild) and os.path.exists(binary_path):
        console.print(
            f"[green]Binary already exists at: {binary_path} (skipping rebuild) [/green]"
        )
        return True

    console.print("[yellow]Binary not found, attempting to build...[/yellow]")

    arch_suffix = detect_arch()
    image_tag = f"{os.path.basename(app_dir)}:latest-{arch_suffix}"

    # Build (or rebuild) the Docker image – this function is idempotent.
    try:
        image_tag = build_docker_image(app_dir, app_name)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        console.print(
            f"[bold red]Error:[/bold red] Failed to build Docker image: {exc}"
        )
        return False

    console.print("[blue]Installing dependencies...[/blue]")
    vcpkg_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{os.path.abspath(app_dir)}:/home/workspace",
        image_tag,
        "/bin/bash",
        "-c",
        "cd /home/workspace && if [ -f vcpkg.json ]; then "
        "echo 'Installing dependencies from vcpkg.json...' && "
        "${VCPKG_ROOT}/vcpkg install --triplet arm64-linux-dynamic-release; fi",
    ]

    try:
        subprocess.run(vcpkg_cmd, check=True, cwd=app_dir)
    except subprocess.CalledProcessError:
        console.print(
            "[yellow]Warning: Failed to install dependencies. The build might still succeed.[/yellow]"
        )

    console.print("[blue]Running build command...[/blue]")

    build_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{os.path.abspath(app_dir)}:/home/workspace",
        image_tag,
        "/bin/bash",
        "-c",
        (
            "cd /home/workspace && "
            "if [ -f CMakePresets.json ]; then "
            "echo 'Using existing CMake presets...' && "
            "cmake --preset=dynamic-aarch64 -DVCPKG_TARGET_TRIPLET='arm64-linux-dynamic-release' && "
            "cmake --build --preset=cross-release -j$(nproc); "
            "else "
            "echo 'No CMake presets found, using manual configuration...' && "
            "export VCPKG_DEFAULT_TRIPLET=arm64-linux-dynamic-release && "
            "cmake -B build-aarch64 -S . "
            "-DCMAKE_TOOLCHAIN_FILE=${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake "
            "-DVCPKG_TARGET_TRIPLET=arm64-linux-dynamic-release "
            "-DVCPKG_INSTALLED_DIR=${VCPKG_ROOT}/vcpkg_installed "
            "-DBUILD_SHARED_LIBS=ON "
            "-DCMAKE_BUILD_TYPE=Release "
            "-DBUILD_FOR_ARM64=ON && "
            "cmake --build build-aarch64 -j$(nproc); "
            "fi"
        ),
    ]

    try:
        subprocess.run(build_cmd, check=True, cwd=app_dir)
    except subprocess.CalledProcessError:
        console.print(
            "[bold red]Error:[/bold red] Failed to build application. Check the CMake output above for details."
        )
        return False

    if os.path.exists(binary_path):
        console.print(f"[green]Successfully built binary at: {binary_path}[/green]")
        return True

    # Fallback: try to locate the binary elsewhere in the tree
    console.print(
        f"[bold yellow]Warning: Build completed but binary not found at expected location: {binary_path}[/bold yellow]"
    )

    try:
        binary_found = subprocess.run(
            [
                "find",
                app_dir,
                "-type",
                "f",
                "-name",
                app_name,
                "-not",
                "-path",
                "*/.*",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()

        if binary_found:
            located = binary_found.split("\n")[0]
            build_dir = os.path.dirname(binary_path)
            os.makedirs(build_dir, exist_ok=True)
            shutil.copy(located, binary_path)
            console.print(
                f"[green]Copied binary from {located} to standard location {binary_path}[/green]"
            )
            return True
    except Exception:
        pass

    return False


def build_deb_package(app_dir: str, app_name: str, version: str = "0.1.0") -> bool:
    """Stage *app_name* and produce a ``.deb`` file within *app_dir*."""

    try:
        staging_dir = tempfile.mkdtemp(prefix="synapse-package-")
        binary_path = os.path.join(app_dir, "build-aarch64", app_name)

        if not os.path.exists(binary_path):
            console.print(
                f"[bold red]Error:[/bold red] Compiled binary '{app_name}' not found at {binary_path}."
            )
            return False

        bin_dst_dir = os.path.join(staging_dir, "opt", "scifi", "bin")
        os.makedirs(bin_dst_dir, exist_ok=True)
        shutil.copy2(binary_path, os.path.join(bin_dst_dir, app_name))

        svc_content = f"""[Unit]
Description=Synapse Application
After=network-online.target
Wants=network-online.target
Requires=systemd-udevd.service
After=systemd-udevd.service

[Service]
Type=simple
User=root
Restart=no
ExecStartPre=/sbin/sysctl -w net.core.wmem_max=4194304
ExecStartPre=/sbin/sysctl -w net.core.wmem_default=4194304
Environment=LD_LIBRARY_PATH=/opt/scifi/usr-libs:/opt/scifi/lib
Environment=SCIFI_ROOT=/opt/scifi
ExecStart=/opt/scifi/bin/{app_name}
WorkingDirectory=/opt/scifi

[Install]
WantedBy=multi-user.target
"""
        svc_dst = os.path.join(
            staging_dir, "etc", "systemd", "system", f"{app_name}.service"
        )
        os.makedirs(os.path.dirname(svc_dst), exist_ok=True)
        with open(svc_dst, "w", encoding="utf-8") as fp:
            fp.write(svc_content)

        lifecycle_scripts_tmp: list[str] = []

        postinstall_path = os.path.join(staging_dir, "postinstall.sh")
        with open(postinstall_path, "w", encoding="utf-8") as fp:
            fp.write("#!/bin/bash\nset -e\nsystemctl daemon-reload\n")
        os.chmod(postinstall_path, 0o755)
        lifecycle_scripts_tmp.append(postinstall_path)

        preremove_path = os.path.join(staging_dir, "preremove.sh")
        with open(preremove_path, "w", encoding="utf-8") as fp:
            fp.write(
                f"#!/bin/bash\nset -e\nsystemctl stop {app_name} || true\nsystemctl disable {app_name} || true\n"
            )
        os.chmod(preremove_path, 0o755)
        lifecycle_scripts_tmp.append(preremove_path)

        postremove_path = os.path.join(staging_dir, "postremove.sh")
        with open(postremove_path, "w", encoding="utf-8") as fp:
            fp.write("#!/bin/bash\nset -e\nsystemctl daemon-reload\n")
        os.chmod(postremove_path, 0o755)
        lifecycle_scripts_tmp.append(postremove_path)

        lib_dst_dir = os.path.join(staging_dir, "opt", "scifi", "lib")
        os.makedirs(lib_dst_dir, exist_ok=True)

        try:
            arch_suffix = detect_arch()
            image_tag = f"{app_name}:latest-{arch_suffix}"
            platform_opt = "linux/arm64" if arch_suffix == "arm64" else "linux/amd64"

            console.print(
                f"[yellow]Extracting SDK libraries from Docker image [bold]{image_tag}[/bold]...[/yellow]"
            )

            docker_cmd = [
                "docker",
                "run",
                "--rm",
                "--platform",
                platform_opt,
                "-v",
                f"{lib_dst_dir}:/out",
                image_tag,
                "/bin/bash",
                "-c",
                "find /usr/lib -name 'libsynapse*.so*' -exec cp -a {} /out/ \\;",
            ]

            subprocess.run(docker_cmd, check=True)

        except subprocess.CalledProcessError as exc:
            console.print(
                f"[bold red]Error:[/bold red] Failed to copy SDK libraries from Docker image: {exc}"
            )
            console.print(
                "[yellow]Falling back to host /usr/lib lookup for libsynapse*.so* (results may be incomplete).[/yellow]"
            )

            for lib in glob.glob("/usr/lib/**/libsynapse*.so*", recursive=True):
                try:
                    shutil.copy2(lib, lib_dst_dir)
                except PermissionError:
                    console.print(f"[yellow]Skipping lib copy (perm): {lib}[/yellow]")

        fpm_cmd = [
            "fpm",
            "-s",
            "dir",
            "-t",
            "deb",
            "-n",
            app_name,
            "-f",
            "-v",
            version,
            "-C",
            staging_dir,
            "--deb-no-default-config-files",
            "--depends",
            "systemd",
            "--vendor",
            "Science Corporation",
            "--description",
            "Synapse Application",
            "--architecture",
            "arm64",
        ]

        # Attach lifecycle scripts
        script_map = {
            "postinstall.sh": "--after-install",
            "preremove.sh": "--before-remove",
            "postremove.sh": "--after-remove",
        }
        for path in lifecycle_scripts_tmp:
            opt = script_map.get(os.path.basename(path))
            if opt:
                container_path = f"/pkg/{os.path.basename(path)}"
                fpm_cmd.extend([opt, container_path])

        fpm_cmd.append(".")

        fpm_image = "cdrx/fpm-ubuntu:latest"
        console.print(
            f"[yellow]Packaging App for Synapse Device (Docker image: {fpm_image}) ...[/yellow]"
        )

        # Replace host-specific staging dir with container mount path
        fpm_args = fpm_cmd[1:]
        try:
            c_index = fpm_args.index("-C") + 1
            fpm_args[c_index] = "/pkg"
        except ValueError:
            pass

        docker_fpm_cmd = [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "-v",
            f"{staging_dir}:/pkg",
            "-v",
            f"{app_dir}:/out",
            "-w",
            "/out",
            fpm_image,
            "fpm",
        ] + fpm_args

        subprocess.run(
            docker_fpm_cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Verify that a .deb was produced
        deb_files = [
            f for f in os.listdir(app_dir) if f.endswith(".deb") and "arm64" in f
        ]
        if not deb_files:
            console.print(
                f"[bold red]Error:[/bold red] FPM completed but no .deb found in {app_dir}."
            )
            return False

        console.print("[green]Package created successfully![/green]")
        return True

    except subprocess.CalledProcessError as exc:
        console.print(f"[bold red]Error:[/bold red] FPM failed: {exc}")
        return False

    finally:
        # "staging_dir" is intentionally *not* deleted so that users can inspect
        # its contents when troubleshooting.  The host's temp directory will
        # eventually clean it up automatically.
        pass


def package_app(app_dir: str, app_name: str) -> bool:
    """Thin wrapper used by callers (e.g., CLI) to build the .deb."""
    return build_deb_package(app_dir, app_name)


def find_deb_package(app_dir: str) -> str | None:
    """Return the path to the .deb generated in *app_dir* or *None*."""
    for file in os.listdir(app_dir):
        if file.endswith(".deb"):
            return os.path.join(app_dir, file)

    console.print(
        f"[bold red]Error:[/bold red] Could not find .deb package in {app_dir}"
    )
    return None


def build_cmd(args) -> None:
    """Handle the ``synapsectl build`` sub-command."""

    if not ensure_docker():
        return

    app_dir = os.path.abspath(args.app_dir)

    manifest = validate_manifest(os.path.join(app_dir, "manifest.json"))
    if not manifest:
        return

    app_name = manifest["name"]
    console.print(f"[bold]Building application:[/bold] [yellow]{app_name}[/yellow]")

    # 1. Build phase (unless explicitly skipped)
    if not args.skip_build:
        if not build_app(app_dir, app_name, force_rebuild=True):
            console.print(
                "[bold red]Error:[/bold red] Failed to build the application."
            )
            return
    else:
        console.print(
            "[yellow]Skipping compile phase as requested (--skip-build).[/yellow]"
        )

    # 2. Package (.deb)
    if not package_app(app_dir, app_name):
        return

    # 3. Locate artefact and present summary panel
    deb_path = find_deb_package(app_dir)
    if not deb_path:
        return

    console.print(
        Panel(
            f"[green]Build complete![/green]\n\nGenerated package: [bold]{deb_path}[/bold]",
            title="Build Successful",
            border_style="green",
            box=box.DOUBLE,
        )
    )


def add_commands(subparsers) -> None:
    """Register the *build* command with the top-level CLI parser."""

    build_parser = subparsers.add_parser(
        "build",
        help="Cross-compile and package an application into a .deb without deploying",
    )
    build_parser.add_argument(
        "app_dir",
        nargs="?",
        default=".",
        help="Path to the application directory (defaults to current working directory)",
    )
    build_parser.add_argument(
        "--skip-build",
        action="store_true",
        default=False,
        help="Skip compilation phase; assume the binary already exists and only build the .deb package.",
    )
    build_parser.set_defaults(func=build_cmd)
