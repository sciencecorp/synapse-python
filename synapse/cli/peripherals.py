"""CLI commands for managing Synapse peripheral plugins.

A peripheral plugin is a shared library (.so) built against scifi-peripheral-sdk
and installed at /usr/lib/scifi/plugins/<name>.so on the device. The scifi-server
daemon scans that directory at startup, dlopens each .so, and dispatches matching
peripheral IDs to the plugin's factory.

Build and deploy mirror `synapsectl apps`:
  - `peripherals build` cross-compiles the .so and packages it (plus
    libscifi-peripheral-sdk.so* extracted from the builder image) into a .deb
    with `Section: synapse-peripherals`.
  - `peripherals deploy` streams that .deb over the existing DeployApp gRPC
    method. scifi-server's install handler accepts either `synapse-apps` or
    `synapse-peripherals` sections and runs `dpkg -i --force-overwrite --force-depends`.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel

from synapse.cli.build import (
    build_docker_image,
    detect_arch,
    ensure_docker,
    find_deb_package,
    validate_manifest,
)
from synapse.cli.deploy import deploy_package

console = Console()

FPM_IMAGE = "cdrx/fpm-ubuntu:latest"
SECTION_LABEL = "synapse-peripherals"


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def add_commands(subparsers: argparse._SubParsersAction):
    """Add the peripherals command group to the CLI."""
    peripherals_parser = subparsers.add_parser(
        "peripherals", help="Build and deploy peripheral plugins to a Synapse device"
    )
    peripherals_subparsers = peripherals_parser.add_subparsers(
        title="Peripheral Commands"
    )

    build_parser = peripherals_subparsers.add_parser(
        "build",
        help="Cross-compile a peripheral plugin into a .so and package it as a .deb",
    )
    build_parser.add_argument(
        "peripheral_dir",
        nargs="?",
        default=".",
        help="Path to the peripheral plugin directory (defaults to cwd)",
    )
    build_parser.add_argument(
        "--clean",
        action="store_true",
        default=False,
        help="Clean build directories before compiling",
    )
    build_parser.set_defaults(func=build_cmd)

    deploy_parser = peripherals_subparsers.add_parser(
        "deploy",
        help=(
            "Install a peripheral plugin .deb on the device via gRPC. "
            "Builds first unless --package is provided."
        ),
    )
    deploy_parser.add_argument(
        "peripheral_dir",
        nargs="?",
        default=".",
        help="Path to the peripheral plugin directory (defaults to cwd)",
    )
    deploy_parser.add_argument(
        "--package",
        "-p",
        type=str,
        default=None,
        help="Path to a pre-built .deb to deploy (skips local build and package steps)",
    )
    deploy_parser.set_defaults(func=deploy_cmd)


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def _expected_so_filename(manifest: dict) -> str:
    """Return the basename of the .so this plugin produces.

    Reads manifest.install.target if present (e.g.
    "/usr/lib/scifi/plugins/intan_rhd2132.so" → "intan_rhd2132.so"),
    otherwise falls back to "<manifest.name>.so".
    """
    install = manifest.get("install") or {}
    target = install.get("target")
    if target:
        return os.path.basename(target)
    return f"{manifest['name']}.so"


# ---------------------------------------------------------------------------
# Build .so
# ---------------------------------------------------------------------------


def build_peripheral_so(
    peripheral_dir: str, plugin_name: str, so_filename: str, clean: bool = False
) -> bool:
    """Cross-compile *plugin_name* into a .so inside its SDK container."""

    console.print(f"[yellow]Building peripheral plugin: {plugin_name}...[/yellow]")
    so_path = os.path.join(peripheral_dir, "build/aarch64", so_filename)

    try:
        image_tag = build_docker_image(peripheral_dir, plugin_name)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        console.print(
            f"[bold red]Error:[/bold red] Failed to build Docker image: {exc}"
        )
        return False

    if clean:
        console.print("[yellow]Cleaning build directories...[/yellow]")
        clean_cmd = [
            "docker", "run", "--rm",
            "-v", f"{os.path.abspath(peripheral_dir)}:/home/workspace",
            image_tag,
            "/bin/bash", "-c",
            "cd /home/workspace && rm -rf build/ || true",
        ]
        try:
            subprocess.run(clean_cmd, check=True, cwd=peripheral_dir)
        except subprocess.CalledProcessError:
            console.print("[yellow]Warning: clean failed; continuing.[/yellow]")

    console.print("[blue]Installing dependencies (vcpkg)...[/blue]")
    vcpkg_cmd = [
        "docker", "run", "--rm",
        "-v", f"{os.path.abspath(peripheral_dir)}:/home/workspace",
        image_tag,
        "/bin/bash", "-c",
        "cd /home/workspace && "
        "if [ -f vcpkg.json ]; then "
        '${VCPKG_ROOT}/vcpkg install --triplet arm64-linux-dynamic-release --x-install-root "$PWD/build/host/vcpkg_installed"; '
        "fi",
    ]
    try:
        subprocess.run(vcpkg_cmd, check=True, cwd=peripheral_dir)
    except subprocess.CalledProcessError:
        console.print(
            "[yellow]Warning: vcpkg install failed; build might still succeed.[/yellow]"
        )

    console.print("[blue]Running cmake build...[/blue]")
    build_cmd_str = (
        "cd /home/workspace && "
        "if [ -f CMakePresets.json ]; then "
        "cmake --preset=dynamic-aarch64 -DVCPKG_TARGET_TRIPLET='arm64-linux-dynamic-release' && "
        "cmake --build --preset=cross-release -j$(nproc); "
        "else "
        "export VCPKG_DEFAULT_TRIPLET=arm64-linux-dynamic-release && "
        "cmake -B build/aarch64 -S . "
        "-DCMAKE_TOOLCHAIN_FILE=${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake "
        "-DVCPKG_TARGET_TRIPLET=arm64-linux-dynamic-release "
        "-DVCPKG_INSTALLED_DIR=${VCPKG_ROOT}/build/host/vcpkg_installed "
        "-DBUILD_SHARED_LIBS=ON "
        "-DCMAKE_BUILD_TYPE=Release "
        "-DBUILD_FOR_ARM64=ON && "
        "cmake --build build/aarch64 -j$(nproc); "
        "fi"
    )
    build_cmd_args = [
        "docker", "run", "--rm",
        "-v", f"{os.path.abspath(peripheral_dir)}:/home/workspace",
        image_tag,
        "/bin/bash", "-c",
        build_cmd_str,
    ]
    try:
        subprocess.run(build_cmd_args, check=True, cwd=peripheral_dir)
    except subprocess.CalledProcessError:
        console.print(
            "[bold red]Error:[/bold red] Build failed. Check the CMake output above."
        )
        return False

    if os.path.exists(so_path):
        console.print(f"[green]Built shared object: {so_path}[/green]")
        return True

    # Fallback locate (CMake OUTPUT_NAME != manifest.install.target basename)
    console.print(
        f"[bold yellow]Warning: {so_filename} not found at {so_path}; searching...[/bold yellow]"
    )
    try:
        found = subprocess.run(
            [
                "find", peripheral_dir, "-type", "f", "-name", so_filename,
                "-not", "-path", "*/.*",
            ],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        if found:
            located = found.split("\n")[0]
            os.makedirs(os.path.dirname(so_path), exist_ok=True)
            shutil.copy(located, so_path)
            console.print(
                f"[green]Copied {located} → {so_path}[/green]"
            )
            return True
    except Exception:
        pass

    console.print(
        f"[bold red]Error:[/bold red] Could not locate {so_filename} after build."
    )
    return False


# ---------------------------------------------------------------------------
# Package .deb
# ---------------------------------------------------------------------------


def build_peripheral_deb(
    peripheral_dir: str, plugin_name: str, so_filename: str, version: str = "0.1.0"
) -> bool:
    """Stage plugin .so + SDK runtime library, then run fpm to produce a .deb.

    Layout inside the .deb:
      /usr/lib/scifi/plugins/<so_filename>   ← the plugin itself
      /usr/lib/libscifi-peripheral-sdk.so.*  ← extracted from the builder image

    Section is set to `synapse-peripherals` so scifi-server's DeployApp gate
    accepts it (sibling accept-list entry next to `synapse-apps`).
    """
    staging_dir = tempfile.mkdtemp(prefix="synapse-peripheral-package-")
    try:
        so_path = os.path.join(peripheral_dir, "build/aarch64", so_filename)
        if not os.path.exists(so_path):
            console.print(
                f"[bold red]Error:[/bold red] Plugin .so not found at {so_path}"
            )
            return False

        # 1. Stage the plugin .so at /usr/lib/scifi/plugins/<name>.so
        plugin_dst = os.path.join(staging_dir, "usr", "lib", "scifi", "plugins")
        os.makedirs(plugin_dst, exist_ok=True)
        shutil.copy2(so_path, os.path.join(plugin_dst, so_filename))

        # 2. Stage libscifi-peripheral-sdk.so* from the builder image at /usr/lib.
        # The SDK ships there via `apt-get install scifi-peripheral-sdk` inside
        # the builder Dockerfile, so it's the same source the linker resolved
        # against at build time — guaranteeing ABI alignment for the plugin.
        sdk_dst = os.path.join(staging_dir, "usr", "lib")
        os.makedirs(sdk_dst, exist_ok=True)

        arch_suffix = detect_arch()
        image_tag = f"{plugin_name}:latest-{arch_suffix}"
        platform_opt = "linux/arm64" if arch_suffix == "arm64" else "linux/amd64"

        console.print(
            f"[yellow]Extracting SDK runtime from Docker image [bold]{image_tag}[/bold]...[/yellow]"
        )
        extract_cmd = [
            "docker", "run", "--rm",
            "--platform", platform_opt,
            "-v", f"{sdk_dst}:/out",
            image_tag,
            "/bin/bash", "-c",
            r"find /usr/lib -maxdepth 1 -name 'libscifi-peripheral-sdk.so*' -exec cp -a {} /out/ \;",
        ]
        try:
            subprocess.run(extract_cmd, check=True)
        except subprocess.CalledProcessError as exc:
            console.print(
                f"[bold red]Error:[/bold red] Failed to extract SDK runtime: {exc}"
            )
            return False

        # 3. Sanity check — make sure the extraction actually copied something.
        sdk_files = [f for f in os.listdir(sdk_dst) if f.startswith("libscifi-peripheral-sdk.so")]
        if not sdk_files:
            console.print(
                "[bold red]Error:[/bold red] SDK runtime libraries not found in builder image. "
                "Make sure your Dockerfile installs scifi-peripheral-sdk."
            )
            return False

        # 4. Postinstall: nudge the user to restart scifi-server.
        # Restarting automatically could interrupt an active recording session,
        # so leave it manual.
        postinstall_path = os.path.join(staging_dir, "postinstall.sh")
        with open(postinstall_path, "w", encoding="utf-8") as fp:
            fp.write(
                "#!/bin/bash\n"
                "set -e\n"
                "echo 'Peripheral plugin installed. Restart scifi-server to load it.'\n"
                "exit 0\n"
            )
        os.chmod(postinstall_path, 0o755)

        # 5. Run fpm inside the cdrx/fpm-ubuntu image (matches apps' packaging path).
        dist_dir = os.path.join(peripheral_dir, "dist")
        os.makedirs(dist_dir, exist_ok=True)

        fpm_args = [
            "fpm",
            "-s", "dir",
            "-t", "deb",
            "-n", plugin_name,
            "-f",
            "-v", version,
            "-C", "/pkg",
            "--deb-no-default-config-files",
            "--vendor", "Science Corporation",
            "--description", "Synapse peripheral plugin",
            "--architecture", "arm64",
            "--category", SECTION_LABEL,
            "--after-install", "/pkg/postinstall.sh",
            ".",
        ]

        console.print(
            f"[yellow]Packaging plugin .deb (Docker image: {FPM_IMAGE}) ...[/yellow]"
        )
        docker_fpm_cmd = [
            "docker", "run", "--rm",
            "--platform", "linux/amd64",
            "-v", f"{staging_dir}:/pkg",
            "-v", f"{dist_dir}:/out",
            "-w", "/out",
            FPM_IMAGE,
        ] + fpm_args

        subprocess.run(
            docker_fpm_cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Verify a .deb actually landed.
        deb_files = [
            f for f in os.listdir(dist_dir) if f.endswith(".deb") and "arm64" in f
        ]
        if not deb_files:
            console.print(
                f"[bold red]Error:[/bold red] fpm completed but no .deb found in {dist_dir}."
            )
            return False

        console.print("[green]Plugin .deb created successfully![/green]")
        return True

    except subprocess.CalledProcessError as exc:
        console.print(f"[bold red]Error:[/bold red] fpm failed: {exc}")
        return False
    # Leave staging_dir on disk for inspection if something goes wrong;
    # /tmp eventually cleans itself.


# ---------------------------------------------------------------------------
# `peripherals build`
# ---------------------------------------------------------------------------


def build_cmd(args) -> None:
    """Handle ``synapsectl peripherals build``."""

    if not ensure_docker():
        return

    peripheral_dir = os.path.abspath(args.peripheral_dir)

    manifest = validate_manifest(os.path.join(peripheral_dir, "manifest.json"))
    if not manifest:
        return

    plugin_name = manifest["name"]
    version = manifest.get("version", "0.1.0")
    so_filename = _expected_so_filename(manifest)

    console.print(
        f"[bold]Building peripheral plugin:[/bold] [yellow]{plugin_name}[/yellow] "
        f"(artifact: [cyan]{so_filename}[/cyan])"
    )

    if not build_peripheral_so(peripheral_dir, plugin_name, so_filename, clean=args.clean):
        return

    if not build_peripheral_deb(peripheral_dir, plugin_name, so_filename, version=version):
        return

    deb_path = find_deb_package(os.path.join(peripheral_dir, "dist"))
    if not deb_path:
        return

    console.print(
        Panel(
            f"[green]Build complete![/green]\n\n"
            f"Plugin: [bold]{plugin_name}[/bold] v{version}\n"
            f"Package: [bold]{deb_path}[/bold]\n\n"
            f"Deploy with: [cyan]synapsectl -u <device> peripherals deploy .[/cyan]",
            title="Build Successful",
            border_style="green",
            box=box.DOUBLE,
        )
    )


# ---------------------------------------------------------------------------
# `peripherals deploy`
# ---------------------------------------------------------------------------


def deploy_cmd(args) -> None:
    """Handle ``synapsectl peripherals deploy`` — gRPC-stream a .deb to the device.

    Reuses apps' DeployApp gRPC method; the scifi-server side accepts plugin
    .debs because their Section (`synapse-peripherals`) is in the install-time
    accept-list. No new RPC, no new install plumbing.
    """

    # --package short-circuit: skip build, deploy the supplied .deb directly.
    if args.package:
        deb_package: Optional[str] = os.path.abspath(args.package)
        if not os.path.exists(deb_package):
            console.print(
                f"[bold red]Error:[/bold red] Provided package not found: {deb_package}"
            )
            return
        console.print(
            f"[bold]Deploying pre-built plugin:[/bold] [yellow]{os.path.basename(deb_package)}[/yellow]"
        )
    else:
        if not ensure_docker():
            return

        peripheral_dir = os.path.abspath(args.peripheral_dir)
        manifest = validate_manifest(os.path.join(peripheral_dir, "manifest.json"))
        if not manifest:
            return

        plugin_name = manifest["name"]
        version = manifest.get("version", "0.1.0")
        so_filename = _expected_so_filename(manifest)

        console.print(
            f"[bold]Deploying peripheral plugin:[/bold] [yellow]{plugin_name}[/yellow]"
        )

        if not build_peripheral_so(peripheral_dir, plugin_name, so_filename):
            return
        if not build_peripheral_deb(peripheral_dir, plugin_name, so_filename, version=version):
            return

        deb_package = find_deb_package(os.path.join(peripheral_dir, "dist"))
        if not deb_package:
            return

    if not args.uri:
        console.print(
            "[yellow]No URI provided. Package created but not deployed.[/yellow]"
        )
        console.print(f"[green]Package available at:[/green] {deb_package}")
        return

    deploy_package(args.uri, deb_package)
