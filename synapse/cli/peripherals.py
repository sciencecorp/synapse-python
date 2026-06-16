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
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel

from synapse.cli import gateware
from synapse.cli.build import (
    build_docker_image,
    detect_arch,
    ensure_docker,
    find_deb_package,
    validate_manifest,
)
from synapse.cli.deploy import deploy_package
from synapse.cli.gateware import LicenseUnsetError

console = Console()

FPM_IMAGE = "cdrx/fpm-ubuntu:latest"
SECTION_LABEL = "synapse-peripherals"


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def _add_half_subcommands(parent_parser, *, func, action_label, extra_args):
    """Wire driver/gateware/both leaf subcommands under *parent_parser*.

    Each leaf carries a ``peripheral_dir`` positional plus whatever per-command
    options *extra_args* installs, and sets ``half`` to its own name so the
    shared handler (*func*) branches on ``args.half`` exactly as it did under
    the old half-selector flags. A bare parent command (no leaf chosen) prints
    its own help. *action_label* is the verb phrase used in each leaf's help
    line ("Build/package", "Build/deploy").
    """
    targets = {
        "driver": "only the driver .so (skips the gateware container)",
        "gateware": "only the FPGA .bit (skips cmake/vcpkg)",
        "both": "both the driver .so and the FPGA .bit",
    }
    half_subparsers = parent_parser.add_subparsers(title="Target")
    for half, what in targets.items():
        leaf = half_subparsers.add_parser(half, help=f"{action_label} {what}.")
        leaf.add_argument(
            "peripheral_dir",
            nargs="?",
            default=".",
            help="Path to the peripheral plugin directory (defaults to cwd)",
        )
        extra_args(leaf)
        leaf.set_defaults(func=func, half=half)
    parent_parser.set_defaults(func=lambda _: parent_parser.print_help())


def add_commands(subparsers: argparse._SubParsersAction):
    """Add the peripherals command group to the CLI."""
    peripherals_parser = subparsers.add_parser(
        "peripherals", help="Build and deploy peripheral plugins to a Synapse device"
    )
    peripherals_subparsers = peripherals_parser.add_subparsers(
        title="Peripheral Commands"
    )

    # `build` / `deploy` each expose driver/gateware/both as subcommands rather
    # than half-selector flags. Each leaf sets `half` to its own name, which is
    # exactly the value build_cmd/deploy_cmd already branch on, so the handlers
    # need no change. A bare `build`/`deploy` (no leaf chosen) prints its help.
    build_parser = peripherals_subparsers.add_parser(
        "build",
        help="Cross-compile a peripheral plugin into a .so/.bit and package it as a .deb",
    )
    _add_half_subcommands(
        build_parser,
        func=build_cmd,
        action_label="Build/package",
        extra_args=lambda leaf: leaf.add_argument(
            "--clean",
            action="store_true",
            default=False,
            help="Clean build directories before compiling",
        ),
    )

    deploy_parser = peripherals_subparsers.add_parser(
        "deploy",
        help=(
            "Install a peripheral plugin .deb on the device via gRPC. "
            "Builds first unless --package is provided."
        ),
    )
    _add_half_subcommands(
        deploy_parser,
        func=deploy_cmd,
        action_label="Build/deploy",
        extra_args=lambda leaf: leaf.add_argument(
            "--package",
            "-p",
            type=str,
            default=None,
            help="Path to a pre-built .deb to deploy (skips local build and package steps)",
        ),
    )

    # `peripherals gateware <verb> [args...]` — pass-through dispatcher to
    # axon-peripheral-sdk inside the gateware container. argparse.REMAINDER
    # captures the entire tail verbatim so the SDK is the sole source of
    # truth for verbs and flags; synapsectl does NOT gate on a known-verb
    # list. peripheral_dir is intentionally NOT a positional here -- REMAINDER
    # would swallow it -- the dispatcher uses os.getcwd() instead.
    #
    # REMAINDER only starts capturing at the first positional, so a LEADING
    # option (e.g. `gateware --install-completion`, a top-level SDK flag) is
    # otherwise rejected by argparse before REMAINDER engages. The
    # `_passthrough_extra` marker tells parse_args_with_passthrough to fold any
    # such leftover tokens into `argv` instead of erroring -- see that helper.
    gateware_parser = peripherals_subparsers.add_parser(
        "gateware",
        help="Pass arguments through to axon-peripheral-sdk inside the gateware container.",
        description=(
            "Forwards the verb and arguments verbatim to axon-peripheral-sdk "
            "inside the gateware container. Run `synapsectl peripherals gateware "
            "<verb> --help` for SDK-side help."
        ),
    )
    gateware_parser.add_argument(
        "argv",
        nargs=argparse.REMAINDER,
        help="SDK verb and its arguments (forwarded verbatim).",
    )
    gateware_parser.set_defaults(func=gateware_cmd, _passthrough_extra=True)


def parse_args_with_passthrough(parser: argparse.ArgumentParser, argv=None):
    """Parse CLI args, folding leftover tokens into a pass-through command's argv.

    Plain ``parser.parse_args`` rejects a leading option after
    ``peripherals gateware`` (e.g. ``--install-completion``) because
    ``argparse.REMAINDER`` only captures from the first positional onward. We
    parse with ``parse_known_args`` instead and, when the selected command is
    flagged ``_passthrough_extra`` (the gateware dispatcher), append the
    leftover tokens to its ``argv`` so they reach the SDK verbatim. For every
    other command, leftovers remain a hard error -- preserving argparse's usual
    ``unrecognized arguments`` behavior and typo-catching.
    """
    args, extra = parser.parse_known_args(argv)
    if extra:
        if getattr(args, "_passthrough_extra", False):
            args.argv = list(getattr(args, "argv", None) or []) + list(extra)
        else:
            parser.error("unrecognized arguments: " + " ".join(extra))
    return args


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
        image_tag = build_docker_image(
            peripheral_dir, "axon-peripheral", roles=["driver"]
        )["driver"]
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        console.print(
            f"[bold red]Error:[/bold red] Failed to build driver Docker image: {exc}"
        )
        return False

    if clean:
        console.print("[yellow]Cleaning build directories...[/yellow]")
        clean_cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{os.path.abspath(peripheral_dir)}:/home/workspace",
            image_tag,
            "/bin/bash",
            "-c",
            "cd /home/workspace && rm -rf build/ || true",
        ]
        try:
            subprocess.run(clean_cmd, check=True, cwd=peripheral_dir)
        except subprocess.CalledProcessError:
            console.print("[yellow]Warning: clean failed; continuing.[/yellow]")

    console.print("[blue]Installing dependencies (vcpkg)...[/blue]")
    vcpkg_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{os.path.abspath(peripheral_dir)}:/home/workspace",
        image_tag,
        "/bin/bash",
        "-c",
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
        "docker",
        "run",
        "--rm",
        "-v",
        f"{os.path.abspath(peripheral_dir)}:/home/workspace",
        image_tag,
        "/bin/bash",
        "-c",
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
                "find",
                peripheral_dir,
                "-type",
                "f",
                "-name",
                so_filename,
                "-not",
                "-path",
                "*/.*",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if found:
            located = found.split("\n")[0]
            os.makedirs(os.path.dirname(so_path), exist_ok=True)
            shutil.copy(located, so_path)
            console.print(f"[green]Copied {located} → {so_path}[/green]")
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


def _run_fpm(
    staging_dir: str, dist_dir: str, fpm_args: list, package_name: str
) -> bool:
    """Run fpm inside the packaging image and verify a .deb landed.

    *fpm_args* is the complete fpm argv (starting with ``"fpm"``). Returns
    False (with console errors, including fpm's stderr) on failure.
    """
    docker_fpm_cmd = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "-v",
        f"{staging_dir}:/pkg",
        "-v",
        f"{dist_dir}:/out",
        "-w",
        "/out",
        FPM_IMAGE,
    ] + fpm_args

    try:
        subprocess.run(
            docker_fpm_cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        console.print(f"[bold red]Error:[/bold red] fpm failed: {exc}")
        if exc.stderr:
            console.print(exc.stderr)
        return False

    deb_files = [
        f
        for f in os.listdir(dist_dir)
        if f.startswith(f"{package_name}_") and f.endswith(".deb")
    ]
    if not deb_files:
        console.print(
            f"[bold red]Error:[/bold red] fpm completed but no {package_name} "
            f".deb found in {dist_dir}."
        )
        return False
    return True


def build_peripheral_deb(
    peripheral_dir: str,
    manifest: dict,
    *,
    so_path: str,
    version: str = "0.1.0",
) -> bool:
    """Stage the driver .so + SDK runtime, then run fpm to produce a .deb.

    Layout inside the .deb:
      /usr/lib/scifi/plugins/<so_basename>
      /usr/lib/libscifi-peripheral-sdk.so.*

    Section is set to `synapse-peripherals` so scifi-server's DeployApp gate
    accepts it (sibling accept-list entry next to `synapse-apps`).
    """
    plugin_name = manifest["name"]
    so_filename = _expected_so_filename(manifest)

    staging_dir = tempfile.mkdtemp(prefix="synapse-peripheral-package-")
    # Leave staging_dir on disk for inspection if something goes wrong;
    # /tmp eventually cleans itself.

    # 1. Stage the plugin .so at /usr/lib/scifi/plugins/<name>.so
    if not os.path.exists(so_path):
        console.print(
            f"[bold red]Error:[/bold red] Plugin .so not found at {so_path}"
        )
        return False
    plugin_dst = os.path.join(staging_dir, "usr", "lib", "scifi", "plugins")
    os.makedirs(plugin_dst, exist_ok=True)
    shutil.copy2(so_path, os.path.join(plugin_dst, so_filename))

    # 2. Stage libscifi-peripheral-sdk.so* from the builder image at /usr/lib.
    # The SDK ships via `apt-get install scifi-peripheral-sdk` inside the
    # builder Dockerfile, so it's the same source the linker resolved against
    # at build time — guaranteeing ABI alignment for the plugin.
    sdk_dst = os.path.join(staging_dir, "usr", "lib")
    os.makedirs(sdk_dst, exist_ok=True)

    # Prefer libs already produced on disk next to the .so (the driver
    # builder may stage them there). Fall back to extracting from the
    # builder image only if none are present locally.
    local_libs_dir = os.path.join(peripheral_dir, "build", "aarch64")
    local_libs = (
        [
            f
            for f in os.listdir(local_libs_dir)
            if f.startswith("libscifi-peripheral-sdk.so")
        ]
        if os.path.isdir(local_libs_dir)
        else []
    )
    if local_libs:
        for fname in local_libs:
            shutil.copy2(
                os.path.join(local_libs_dir, fname),
                os.path.join(sdk_dst, fname),
            )
    else:
        try:
            image_tag = build_docker_image(
                peripheral_dir, "axon-peripheral", roles=["driver"]
            )["driver"]
        except (
            subprocess.CalledProcessError,
            FileNotFoundError,
            KeyError,
        ) as exc:
            console.print(
                f"[bold red]Error:[/bold red] Failed to build driver Docker image: {exc}"
            )
            return False
        arch_suffix = detect_arch()
        platform_opt = (
            "linux/arm64" if arch_suffix == "arm64" else "linux/amd64"
        )

        console.print(
            f"[yellow]Extracting SDK runtime from Docker image [bold]{image_tag}[/bold]...[/yellow]"
        )
        extract_cmd = [
            "docker",
            "run",
            "--rm",
            "--platform",
            platform_opt,
            "-v",
            f"{sdk_dst}:/out",
            image_tag,
            "/bin/bash",
            "-c",
            r"find /usr/lib -maxdepth 1 -name 'libscifi-peripheral-sdk.so*' -exec cp -a {} /out/ \;",
        ]
        try:
            subprocess.run(extract_cmd, check=True)
        except subprocess.CalledProcessError as exc:
            console.print(
                f"[bold red]Error:[/bold red] Failed to extract SDK runtime: {exc}"
            )
            return False

        sdk_files = [
            f
            for f in os.listdir(sdk_dst)
            if f.startswith("libscifi-peripheral-sdk.so")
        ]
        if not sdk_files:
            console.print(
                "[bold red]Error:[/bold red] SDK runtime libraries not found in builder image. "
                "Make sure your Dockerfile installs scifi-peripheral-sdk."
            )
            return False

    # 3. Postinstall: nudge the user to restart scifi-server.
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
    # 0o644 is sufficient: fpm embeds this file's *contents* as the .deb's
    # postinst maintainer script (via --after-install), and dpkg makes
    # maintainer scripts executable itself at install time. The staging
    # file's own exec bit never reaches the package.
    os.chmod(postinstall_path, 0o644)

    # 4. Run fpm inside the cdrx/fpm-ubuntu image (matches apps' packaging path).
    dist_dir = os.path.join(peripheral_dir, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    fpm_args = [
        "fpm",
        "-s",
        "dir",
        "-t",
        "deb",
        "-n",
        plugin_name,
        "-f",
        "-v",
        version,
        "-C",
        "/pkg",
        "--deb-no-default-config-files",
        "--vendor",
        "Science Corporation",
        "--description",
        "Synapse peripheral plugin",
        "--architecture",
        "arm64",
        "--category",
        SECTION_LABEL,
        "--after-install",
        "/pkg/postinstall.sh",
        # Input is "usr" (not ".") so postinstall.sh is NOT packaged as a
        # payload file — the -gateware deb installs alongside this one,
        # and two packages shipping /postinstall.sh would dpkg-conflict.
        "usr",
    ]

    console.print(
        f"[yellow]Packaging plugin .deb (Docker image: {FPM_IMAGE}) ...[/yellow]"
    )
    if not _run_fpm(staging_dir, dist_dir, fpm_args, plugin_name):
        return False

    console.print("[green]Plugin .deb created successfully![/green]")
    return True


# Gateware debs are keyed by the bitstream identifier (not the plugin), so
# redeploying the same identifier from any repo replaces the previous
# install instead of dpkg-conflicting with it.
GATEWARE_DEB_PREFIX = "axon-gateware-"
# Owns /opt/scifi/bitstreams and the canonical manifest the fragment's
# relative `artifact` resolves against.
BITSTREAMS_PACKAGE = "axonprobe-bitstreams"


def _gateware_package_name(identifier: str) -> str:
    """Debianize the bitstream identifier into the gateware package name."""
    return f"{GATEWARE_DEB_PREFIX}{identifier.lower().replace('_', '-')}"


def build_gateware_deb(
    peripheral_dir: str,
    manifest: dict,
    *,
    bit_path: str,
    usb_pid: int,
    bitstream_name: Optional[str] = None,
    git_hash: Optional[str] = None,
    version: str = "0.1.0",
) -> bool:
    """Stage the custom bitstream + manifest fragment, then fpm a .deb.

    The deb package is named ``axon-gateware-<debianized-identifier>`` where
    the identifier is ``bitstream_name`` (falling back to the plugin name).
    On-device files land at:
      /opt/scifi/bitstreams/custom/<identifier>.bit
      /opt/scifi/bitstreams/custom/<identifier>.manifest.json

    The fragment carries ``{"name", "usb_pid", "artifact"}`` (plus
    ``"git_hash"`` when provided) with ``artifact`` relative to
    /opt/scifi/bitstreams (canonical-manifest convention). Redeploying the
    same identifier from any repo replaces the previous install (dpkg
    override semantics) instead of conflicting with a plugin-name-keyed
    package. scifi-probe-updater globs custom/*.manifest.json to list
    flashable custom gateware per probe.
    """
    plugin_name = manifest["name"]
    identifier = bitstream_name or plugin_name
    package_name = _gateware_package_name(identifier)

    if not os.path.exists(bit_path):
        console.print(
            f"[bold red]Error:[/bold red] Gateware .bit not found at {bit_path}"
        )
        return False

    staging_dir = tempfile.mkdtemp(prefix="synapse-gateware-package-")
    # Leave staging_dir on disk for inspection if something goes wrong;
    # /tmp eventually cleans itself.

    custom_dir = os.path.join(staging_dir, "opt", "scifi", "bitstreams", "custom")
    os.makedirs(custom_dir, exist_ok=True)
    shutil.copy2(bit_path, os.path.join(custom_dir, f"{identifier}.bit"))

    fragment: dict = {
        "name": identifier,
        "usb_pid": usb_pid,
        "artifact": f"custom/{identifier}.bit",
    }
    if git_hash:
        fragment["git_hash"] = git_hash
    fragment_path = os.path.join(custom_dir, f"{identifier}.manifest.json")
    with open(fragment_path, "w", encoding="utf-8") as fp:
        json.dump(fragment, fp, indent=2)
        fp.write("\n")

    postinstall_path = os.path.join(staging_dir, "postinstall.sh")
    with open(postinstall_path, "w", encoding="utf-8") as fp:
        fp.write(
            "#!/bin/bash\n"
            "set -e\n"
            "echo 'Custom gateware installed. Flash probes from the device "
            "UI (Probe Updates) or scifi-probe-updater.'\n"
            "exit 0\n"
        )
    # Contents are embedded as the deb's postinst (via --after-install);
    # dpkg makes maintainer scripts executable itself.
    os.chmod(postinstall_path, 0o644)

    dist_dir = os.path.join(peripheral_dir, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    # Input is "opt" (not ".") so postinstall.sh is NOT packaged as a
    # payload file — the driver deb installs alongside this one, and two
    # packages shipping /postinstall.sh would dpkg-conflict.
    fpm_args = [
        "fpm",
        "-s",
        "dir",
        "-t",
        "deb",
        "-n",
        package_name,
        "-f",
        "-v",
        version,
        "-C",
        "/pkg",
        "--deb-no-default-config-files",
        "--vendor",
        "Science Corporation",
        "--description",
        "Synapse peripheral custom gateware",
        "--architecture",
        "arm64",
        "--category",
        SECTION_LABEL,
        "--depends",
        BITSTREAMS_PACKAGE,
        "--after-install",
        "/pkg/postinstall.sh",
        "opt",
    ]

    console.print(
        f"[yellow]Packaging gateware .deb (Docker image: {FPM_IMAGE}) ...[/yellow]"
    )
    if not _run_fpm(staging_dir, dist_dir, fpm_args, package_name):
        return False

    console.print("[green]Gateware .deb created successfully![/green]")
    return True


# ---------------------------------------------------------------------------
# Gateware half helpers
# ---------------------------------------------------------------------------


def _clean_gateware_tree(peripheral_dir: str, gateware_image_tag: str) -> None:
    """Wipe ``<peripheral_dir>/src/gateware/build/`` via a docker run.

    Mirrors the driver-side clean in :func:`build_peripheral_so`: it runs the
    rm inside the gateware container so the host user does not need to chown
    files written as the in-container ``dev`` user.
    """
    console.print("[yellow]Cleaning gateware build directory...[/yellow]")
    clean_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{os.path.abspath(peripheral_dir)}:/home/workspace",
        gateware_image_tag,
        "/bin/bash",
        "-c",
        "cd /home/workspace && rm -rf src/gateware/build || true",
    ]
    try:
        subprocess.run(clean_cmd, check=True, cwd=peripheral_dir)
    except subprocess.CalledProcessError:
        console.print("[yellow]Warning: gateware clean failed; continuing.[/yellow]")


def _run_gateware_half(peripheral_dir: str) -> Optional[str]:
    """Run the gateware build half; return the emitted ``.bit`` path or None."""
    try:
        image_tag = build_docker_image(
            peripheral_dir, "axon-peripheral", roles=["gateware"]
        )["gateware"]
    except (subprocess.CalledProcessError, FileNotFoundError, KeyError) as exc:
        console.print(
            f"[bold red]Error:[/bold red] Failed to build gateware Docker image: {exc}"
        )
        return None

    try:
        return gateware.run_gateware_build(peripheral_dir, image_tag)
    except LicenseUnsetError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return None
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        console.print(f"[bold red]Error:[/bold red] Gateware build failed: {exc}")
        return None


def _gateware_usb_pid(bit_path: str) -> Optional[int]:
    """Read the probe USB product id from the bitstream's summary, or None."""
    try:
        return gateware.read_usb_pid(bit_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return None


def _build_debs(
    peripheral_dir: str, manifest: dict, half: str, *, clean: bool = False
) -> Optional[list]:
    """Build the requested halves; return built .deb paths or None on failure.

    Driver deb first, then the -gateware deb — deploy streams them in this
    order so the plugin lands before its gateware shows up as flashable.
    """
    plugin_name = manifest["name"]
    version = manifest.get("version", "0.1.0")
    do_driver = half in ("driver", "both")
    do_gateware = half in ("gateware", "both")
    dist_dir = os.path.join(peripheral_dir, "dist")
    debs: list = []

    if do_gateware and clean:
        try:
            gateware_image_tag = build_docker_image(
                peripheral_dir, "axon-peripheral", roles=["gateware"]
            )["gateware"]
        except (subprocess.CalledProcessError, FileNotFoundError, KeyError) as exc:
            console.print(
                f"[bold red]Error:[/bold red] Failed to build gateware Docker image: {exc}"
            )
            return None
        _clean_gateware_tree(peripheral_dir, gateware_image_tag)

    if do_driver:
        so_filename = _expected_so_filename(manifest)
        if not build_peripheral_so(
            peripheral_dir, plugin_name, so_filename, clean=clean
        ):
            return None
        so_path = os.path.join(peripheral_dir, "build/aarch64", so_filename)
        if not build_peripheral_deb(
            peripheral_dir, manifest, so_path=so_path, version=version
        ):
            return None
        deb = find_deb_package(dist_dir, f"{plugin_name}_{version}")
        if deb is None:
            return None
        debs.append(deb)

    if do_gateware:
        bit_path = _run_gateware_half(peripheral_dir)
        if bit_path is None:
            return None
        usb_pid = _gateware_usb_pid(bit_path)
        if usb_pid is None:
            return None
        identifier = gateware.read_identifier(bit_path) or plugin_name
        if not build_gateware_deb(
            peripheral_dir,
            manifest,
            bit_path=bit_path,
            usb_pid=usb_pid,
            version=version,
            bitstream_name=identifier,
            git_hash=gateware.read_git_sha(bit_path),
        ):
            return None
        deb = find_deb_package(dist_dir, f"{_gateware_package_name(identifier)}_{version}")
        if deb is None:
            return None
        debs.append(deb)

    return debs


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

    console.print(
        f"[bold]Building peripheral plugin:[/bold] [yellow]{manifest['name']}[/yellow]"
    )

    debs = _build_debs(
        peripheral_dir, manifest, getattr(args, "half", "both"), clean=args.clean
    )
    if debs is None:
        return

    package_lines = "\n".join(f"Package: [bold]{d}[/bold]" for d in debs)
    console.print(
        Panel(
            f"[green]Build complete![/green]\n\n"
            f"Plugin: [bold]{manifest['name']}[/bold] "
            f"v{manifest.get('version', '0.1.0')}\n"
            f"{package_lines}\n\n"
            f"Deploy with: [cyan]synapsectl -u <device> peripherals deploy "
            f"{getattr(args, 'half', 'both')} .[/cyan]",
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

    half = getattr(args, "half", "both")

    # --package short-circuit: skip build, deploy the supplied .deb directly.
    if args.package:
        if half != "both":
            console.print(
                f"[yellow]Warning: --{half} ignored when --package is provided; "
                f"deploying the supplied .deb as-is.[/yellow]"
            )
        deb_packages = [os.path.abspath(args.package)]
        if not os.path.exists(deb_packages[0]):
            console.print(
                f"[bold red]Error:[/bold red] Provided package not found: {deb_packages[0]}"
            )
            return
        console.print(
            f"[bold]Deploying pre-built plugin:[/bold] [yellow]{os.path.basename(deb_packages[0])}[/yellow]"
        )
    else:
        if not ensure_docker():
            return

        peripheral_dir = os.path.abspath(args.peripheral_dir)
        manifest = validate_manifest(os.path.join(peripheral_dir, "manifest.json"))
        if not manifest:
            return

        console.print(
            f"[bold]Deploying peripheral plugin:[/bold] [yellow]{manifest['name']}[/yellow]"
        )

        debs = _build_debs(peripheral_dir, manifest, half)
        if debs is None:
            return
        deb_packages = debs

    if not args.uri:
        console.print(
            "[yellow]No URI provided. Package(s) created but not deployed.[/yellow]"
        )
        for deb in deb_packages:
            console.print(f"[green]Package available at:[/green] {deb}")
        return

    for deb in deb_packages:
        if not deploy_package(args.uri, deb):
            console.print(
                f"[bold red]Error:[/bold red] Deploy failed for {deb}; "
                "skipping any remaining packages."
            )
            return


# ---------------------------------------------------------------------------
# `peripherals gateware <verb> [args...]` pass-through dispatcher
# ---------------------------------------------------------------------------


def gateware_cmd(args) -> None:
    """Handle ``synapsectl peripherals gateware <verb> [args...]``.

    Forwards ``args.argv`` (captured by ``argparse.REMAINDER``) verbatim to
    ``axon-peripheral-sdk`` inside the gateware container. The handler
    always terminates via ``sys.exit`` so the SDK's exit code propagates
    cleanly up to the shell.

    Order of operations (mirrors the plan's AC-13 spec):

    1. Resolve LM_LICENSE_FILE -> docker flags. Forwarded when set; when unset
       the SDK runs WITHOUT license args (only Radiant verbs like `build` need
       a license, and the SDK enforces that itself) -- no short-circuit here.
    2. Resolve the peripheral dir to ``os.getcwd()``. REMAINDER captures
       every token after ``gateware``, so a positional ``peripheral_dir``
       cannot coexist with the pass-through; cwd is the only sensible default.
    3. Require ``Dockerfiles/gateware.Dockerfile`` so the user gets a clear
       error before the docker build attempts a missing context.
    4. Build / fetch the gateware image tag via :func:`build_docker_image`.
    5. Delegate to :func:`gateware._gateware_passthrough` and ``sys.exit`` on
       its return code.
    """
    # Forward the Radiant license when set, but do NOT require it: the
    # pass-through must stay usable for verbs that don't touch Radiant
    # (help/doctor/list-profiles/generate/validate/sim). Only `build` runs
    # Radiant, and the SDK's build preflight owns the "license required" error.
    #
    # Unset -> run with no license args, silently. Set-but-bad (a file path
    # that doesn't exist makes build_license_docker_args raise FileNotFoundError
    # from Path.resolve(strict=True)) -> warn so the misconfig isn't masked, but
    # still omit the args and continue, so non-Radiant verbs work and `build`
    # fails SDK-side with clear guidance.
    try:
        license_args = gateware.build_license_docker_args(os.environ)
    except LicenseUnsetError:
        license_args = []
    except FileNotFoundError as exc:
        console.print(
            f"[yellow]Warning:[/yellow] LM_LICENSE_FILE is set but its license "
            f"file was not found ({exc}); continuing without a license. Radiant "
            f"commands (e.g. `build`) will fail until it points at a real file."
        )
        license_args = []

    peripheral_dir = os.path.abspath(os.getcwd())

    dockerfile = Path(peripheral_dir) / "Dockerfiles" / "gateware.Dockerfile"
    if not dockerfile.exists():
        console.print(
            "[bold red]Error:[/bold red] No gateware Dockerfile found at "
            f"{dockerfile}. The `gateware` subcommand requires "
            "Dockerfiles/gateware.Dockerfile in the peripheral plugin directory."
        )
        sys.exit(1)

    try:
        tags = build_docker_image(peripheral_dir, "axon-peripheral", roles=["gateware"])
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        console.print(
            f"[bold red]Error:[/bold red] Failed to build gateware Docker image: {exc}"
        )
        sys.exit(1)

    if "gateware" not in tags:
        console.print(
            "[bold red]Error:[/bold red] build_docker_image returned no 'gateware' "
            "tag; cannot run the gateware pass-through."
        )
        sys.exit(1)

    sys.exit(
        gateware._gateware_passthrough(
            argv=list(args.argv),
            peripheral_dir=peripheral_dir,
            license_args=license_args,
            gateware_image_tag=tags["gateware"],
        )
    )
