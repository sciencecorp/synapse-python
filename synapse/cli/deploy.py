import os
import subprocess
import shutil
import json
import logging
import tempfile
import glob
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Prompt
from rich import box

import synapse.client.sftp as sftp

# Set up console for normal output and a separate one for logs
console = Console()
log_console = Console(stderr=True)

# Configure logging for paramiko to be less verbose
logging.getLogger("paramiko").setLevel(logging.WARNING)


def validate_manifest(manifest_path):
    """Validate the manifest file exists and has required properties"""
    try:
        with open(manifest_path, "r") as f:
            manifest = json.load(f)

        # Basic validation
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


def build_deb_package(app_dir: str, app_name: str, version: str = "0.1.0") -> bool:
    """Create a *.deb* package for *app_name* and place it in *app_dir*.

    Returns ``True`` on success, ``False`` otherwise.
    """

    try:
        staging_dir = tempfile.mkdtemp(prefix="synapse-package-")

        # ------------------------------------------------------------------
        # 1. Locate the compiled binary and copy it to /opt/scifi/bin
        # ------------------------------------------------------------------
        possible_bins = [
            os.path.join(app_dir, "build-aarch64", app_name),
            os.path.join(app_dir, "build", app_name),
            os.path.join(app_dir, "build-arm64", app_name),
        ]

        binary_path = next((p for p in possible_bins if os.path.exists(p)), None)

        if binary_path is None:
            console.print(
                f"[bold red]Error:[/bold red] Compiled binary '{app_name}' not found."
            )
            return False

        bin_dst_dir = os.path.join(staging_dir, "opt", "scifi", "bin")
        os.makedirs(bin_dst_dir, exist_ok=True)
        shutil.copy2(binary_path, os.path.join(bin_dst_dir, app_name))

        # ------------------------------------------------------------------
        # 2. Generate systemd service & lifecycle scripts on the fly
        # ------------------------------------------------------------------

        # Generate systemd unit
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
        with open(svc_dst, "w", encoding="utf-8") as f:
            f.write(svc_content)

        lifecycle_scripts_tmp = []

        postinstall_path = os.path.join(staging_dir, "postinstall.sh")
        with open(postinstall_path, "w", encoding="utf-8") as f:
            f.write("#!/bin/bash\nset -e\nsystemctl daemon-reload\n")
        os.chmod(postinstall_path, 0o755)
        lifecycle_scripts_tmp.append(postinstall_path)

        preremove_path = os.path.join(staging_dir, "preremove.sh")
        with open(preremove_path, "w", encoding="utf-8") as f:
            f.write(
                f"#!/bin/bash\nset -e\nsystemctl stop {app_name} || true\nsystemctl disable {app_name} || true\n"
            )
        os.chmod(preremove_path, 0o755)
        lifecycle_scripts_tmp.append(preremove_path)

        postremove_path = os.path.join(staging_dir, "postremove.sh")
        with open(postremove_path, "w", encoding="utf-8") as f:
            f.write("#!/bin/bash\nset -e\nsystemctl daemon-reload\n")
        os.chmod(postremove_path, 0o755)
        lifecycle_scripts_tmp.append(postremove_path)

        # ------------------------------------------------------------------
        # 3. Copy user-space Synapse SDK shared libs
        # ------------------------------------------------------------------
        lib_dst_dir = os.path.join(staging_dir, "opt", "scifi", "lib")
        os.makedirs(lib_dst_dir, exist_ok=True)
        for lib in glob.glob("/usr/lib/libsynapse*.so*"):
            try:
                shutil.copy2(lib, lib_dst_dir)
            except PermissionError:
                console.print(f"[yellow]Skipping lib copy (perm): {lib}[/yellow]")

        # ------------------------------------------------------------------
        # 4. Build the .deb with FPM
        # ------------------------------------------------------------------
        arch = detect_arch()

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
            arch,
        ]

        # Attach lifecycle scripts (referenced relative to /pkg inside container)
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

        # ------------------------------------------------------------------
        # 5. Invoke FPM in a Docker container (consistent across hosts)
        # ------------------------------------------------------------------

        fpm_image = "cdrx/fpm-ubuntu:latest"
        console.print(f"[yellow]Running FPM (Docker image: {fpm_image}) ...[/yellow]")

        # Replace the host-specific staging dir with the container mount path
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

        subprocess.run(docker_fpm_cmd, check=True)

        # Verify that a .deb was produced
        deb_files = [f for f in os.listdir(app_dir) if f.endswith(".deb")]
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
        pass


def package_app(app_dir, app_name):
    """Package *app_name* into a .deb using the pure-Python builder."""

    return build_deb_package(app_dir, app_name)


def find_deb_package(app_dir):
    """Find the generated .deb package in the app directory"""
    for file in os.listdir(app_dir):
        if file.endswith(".deb"):
            return os.path.join(app_dir, file)

    console.print(
        f"[bold red]Error:[/bold red] Could not find .deb package in {app_dir}"
    )
    return None


def get_device_credentials(ip_address):
    """Get user credentials with clear prompts"""
    console.print()
    console.print(
        Panel(
            f"[bold yellow]Device Connection Details[/bold yellow]\n[white]Target device:[/white] [green]{ip_address}[/green]",
            border_style="blue",
        )
    )

    username = Prompt.ask("Enter login username", default="scifi")

    import getpass

    console.print(
        "[bold blue]Enter login password (input will be hidden):[/bold blue]", end=" "
    )
    login_password = getpass.getpass("")

    console.print(
        "[bold blue]Enter root password for package installation (input will be hidden):[/bold blue]",
        end=" ",
    )
    root_password = getpass.getpass("")

    console.print()
    return username, login_password, root_password


def deploy_package(ip_address, deb_package_path):
    """Deploy the package to the device"""
    package_filename = os.path.basename(deb_package_path)
    console.clear_live()

    # Get cached credentials or prompt for new ones
    cached_ip, username, login_password, root_password = load_cached_credentials()

    # If no cached credentials or they don't match our target IP, prompt for new ones
    if (
        not cached_ip
        or cached_ip != ip_address
        or not username
        or not login_password
        or not root_password
    ):
        username, login_password, root_password = get_device_credentials(ip_address)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}[/bold blue]"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
        refresh_per_second=4,
    ) as progress:
        deploy_task = progress.add_task(
            f"[yellow]Deploying to {ip_address}...", total=3
        )

        try:
            shell = None

            # Connect to the device (connection task)
            connect_task = progress.add_task("[green]Connecting to device...", total=1)
            client, sftp_conn = sftp.connect_sftp(
                hostname=ip_address, username=username, password=login_password
            )
            progress.update(connect_task, completed=1)
            progress.update(deploy_task, advance=1)
            if client is None or sftp_conn is None:
                progress.update(connect_task, visible=False)
                console.print(f"[bold red]Error connecting to {ip_address}[/bold red]")
                console.print(
                    "[yellow]Please check your username and password.[/yellow]"
                )
                return False

            # Upload file task
            upload_task = progress.add_task("[cyan]Uploading package...", total=1)

            try:
                # Create SFTP client and upload
                remote_path = f"/tmp/{package_filename}"
                sftp_conn.put(deb_package_path, remote_path)
                progress.update(upload_task, completed=1)
                progress.update(deploy_task, advance=1)
            except Exception as e:
                progress.update(upload_task, visible=False)
                console.print(f"[bold red]Error uploading package:[/bold red] {str(e)}")
                return False

            # Install task
            install_task = progress.add_task("[magenta]Installing package...", total=1)
            progress.stop()

            try:
                import time

                def run_remote(cmd: str, needs_password: bool = False):
                    """Execute *cmd* over SSH, stream live output, and return (exit_status, full_output).

                    If *needs_password* is True the helper waits until a password
                    prompt is detected before writing *root_password* to *stdin*.
                    This behaves well for environments that rely solely on
                    *su* for privilege escalation because writing the
                    password too early can cause *su* to ignore it and block
                    indefinitely.
                    """
                    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)

                    output = ""
                    pw_sent = False
                    buf_out = ""
                    buf_err = ""

                    def maybe_print(line: str, *, is_err: bool = False):
                        """Filter *line* and print if it should be visible."""
                        clean = line.replace("\r", "")

                        if "Reading database" in clean:
                            return

                        if is_err:
                            log_console.print(clean, style="red", end="")
                        else:
                            log_console.print(clean, end="")

                    while not stdout.channel.exit_status_ready():
                        while stdout.channel.recv_ready():
                            chunk = stdout.channel.recv(1024).decode(errors="replace")
                            output += chunk

                            if (
                                needs_password
                                and ("password" in chunk.lower())
                                and not pw_sent
                            ):
                                stdin.write(root_password + "\n")
                                stdin.flush()
                                pw_sent = True

                            buf_out += chunk
                            while "\n" in buf_out:
                                line, buf_out = buf_out.split("\n", 1)
                                maybe_print(line + "\n", is_err=False)

                        while stderr.channel.recv_ready():
                            chunk = stderr.channel.recv(1024).decode(errors="replace")
                            output += chunk

                            if (
                                needs_password
                                and ("password" in chunk.lower())
                                and not pw_sent
                            ):
                                stdin.write(root_password + "\n")
                                stdin.flush()
                                pw_sent = True

                            buf_err += chunk
                            while "\n" in buf_err:
                                line, buf_err = buf_err.split("\n", 1)
                                maybe_print(line + "\n", is_err=True)

                        time.sleep(0.1)

                    if buf_out:
                        maybe_print(buf_out, is_err=False)
                        buf_out = ""
                    if buf_err:
                        maybe_print(buf_err, is_err=True)
                        buf_err = ""

                    output += stdout.read().decode()
                    output += stderr.read().decode()
                    exit_status = stdout.channel.recv_exit_status()
                    return exit_status, output

                # If we are already root, skip any privilege escalation
                if username == "root":
                    esc_cmd = f"DEBIAN_FRONTEND=noninteractive dpkg -i {remote_path} && rm {remote_path}"
                    exit_status, output = run_remote(esc_cmd)
                else:
                    # Elevate privileges with su (target devices never have sudo)
                    su_cmd = f"su -c 'env DEBIAN_FRONTEND=noninteractive dpkg -i {remote_path} && rm {remote_path}'"
                    exit_status, output = run_remote(su_cmd, needs_password=True)

                # Restart the live progress display now that installation is
                # complete so subsequent updates render properly.
                progress.start()

                if exit_status != 0:
                    progress.update(install_task, visible=False)
                    progress.update(deploy_task, visible=False)
                    console.print(
                        Panel(
                            f"[bold red]Installation Error[/bold red]\n\n{output}",
                            title="Deployment Failed",
                            border_style="red",
                            box=box.DOUBLE,
                        )
                    )
                    return False

                progress.update(install_task, completed=1)
                progress.update(deploy_task, advance=1)

                save_credentials(ip_address, username, login_password, root_password)

                progress.stop()
                console.clear_live()

                console.print(
                    Panel(
                        f"[bold green]Successfully deployed[/bold green] [yellow]{package_filename}[/yellow] [bold green]to[/bold green] [blue]{ip_address}[/blue]",
                        title="Deployment Successful",
                        border_style="green",
                        box=box.DOUBLE,
                    )
                )
                return True

            except Exception as e:
                progress.start()
                progress.update(install_task, visible=False)
                progress.update(deploy_task, visible=False)
                console.print(
                    f"[bold red]Error during installation:[/bold red] {str(e)}"
                )
                return False

        except Exception as e:
            progress.update(deploy_task, visible=False)
            console.print(f"[bold red]Error:[/bold red] Failed to deploy package: {e}")
            return False
        finally:
            # Clean up connections
            try:
                sftp.close_sftp(client, sftp_conn)
                if shell is not None:
                    shell.close()
            except Exception:
                pass


def load_cached_credentials():
    """Load cached credentials from the config file"""
    cache_file = ".synapse_deploy_cache.json"
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                data = json.load(f)
                ip_address = data.get("ip_address")
                username = data.get("username", "scifi")
                encoded_login_password = data.get("encoded_login_password")
                encoded_root_password = data.get("encoded_root_password")

                if encoded_login_password and encoded_root_password:
                    import base64

                    login_password = base64.b64decode(encoded_login_password).decode(
                        "utf-8"
                    )
                    root_password = base64.b64decode(encoded_root_password).decode(
                        "utf-8"
                    )
                    console.print(
                        f"[green]Using cached credentials for [bold]{username}@{ip_address}[/bold][/green]"
                    )
                    return ip_address, username, login_password, root_password
    except Exception as e:
        console.print(
            f"[yellow]Warning: Failed to load cached credentials: {e}[/yellow]"
        )
    return None, None, None, None


def save_credentials(ip_address, username, login_password, root_password):
    """Save credentials to cache file"""
    cache_file = ".synapse_deploy_cache.json"
    try:
        import base64

        with open(cache_file, "w") as f:
            data = {
                "ip_address": ip_address,
                "username": username,
                "encoded_login_password": base64.b64encode(
                    login_password.encode("utf-8")
                ).decode("utf-8"),
                "encoded_root_password": base64.b64encode(
                    root_password.encode("utf-8")
                ).decode("utf-8"),
            }
            json.dump(data, f)
        os.chmod(cache_file, 0o600)  # Restrict file permissions
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to save credentials: {e}[/yellow]")


def build_app(app_dir, app_name):
    """Build the application binary before packaging"""
    console.print(f"[yellow]Building application: {app_name}...[/yellow]")

    # Check if binary already exists
    binary_paths = [
        os.path.join(app_dir, "build-aarch64", app_name),
        os.path.join(app_dir, "build", app_name),
        os.path.join(app_dir, "build-arm64", app_name),
        os.path.join(app_dir, "out", app_name),
    ]

    for path in binary_paths:
        if os.path.exists(path):
            console.print(f"[green]Binary already exists at: {path}[/green]")
            return True

    # Binary doesn't exist, build it
    console.print("[yellow]Binary not found, attempting to build...[/yellow]")

    # Detect architecture
    tag_suffix = detect_arch()

    # Image name
    image = f"{os.path.basename(app_dir)}:latest-{tag_suffix}"

    # Docker image doesn't exist, build it
    console.print(
        f"[yellow]Docker image {image} not found, building it first...[/yellow]"
    )

    # Build the Docker image directly via Python helper
    try:
        image = build_docker_image(app_dir, app_name)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        console.print(f"[bold red]Error:[/bold red] Failed to build Docker image: {e}")
        return False

    # Now build the app in Docker
    console.print("[yellow]Building application in Docker container...[/yellow]")
    console.print(
        "[dim]This may take a few minutes. You'll see output during the build process.[/dim]"
    )

    # First, try to run vcpkg to install dependencies
    vcpkg_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{os.path.abspath(app_dir)}:/home/workspace",
        image,
        "/bin/bash",
        "-c",
        "cd /home/workspace && if [ -f vcpkg.json ]; then echo 'Installing dependencies from vcpkg.json...'; ${VCPKG_ROOT}/vcpkg install --triplet arm64-linux-dynamic-release; fi",
    ]

    try:
        console.print("[blue]Installing dependencies...[/blue]")
        subprocess.run(vcpkg_cmd, check=True, cwd=app_dir)
    except subprocess.CalledProcessError:
        console.print(
            "[yellow]Warning: Failed to install dependencies. The build might still succeed.[/yellow]"
        )

    # Now run the actual build command with a proper CMake preset
    build_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{os.path.abspath(app_dir)}:/home/workspace",
        image,
        "/bin/bash",
        "-c",
        """cd /home/workspace &&
        if [ -f CMakePresets.json ]; then
            # Use the existing presets if available
            echo 'Using existing CMake presets...' &&
            cmake --preset=dynamic-aarch64 -DVCPKG_TARGET_TRIPLET="arm64-linux-dynamic-release" &&
            cmake --build --preset=cross-release -j$(nproc);
        else
            # Fall back to manual configuration
            echo 'No CMake presets found, using manual configuration...' &&
            export VCPKG_DEFAULT_TRIPLET=arm64-linux-dynamic-release &&
            cmake -B build -S . \
            -DCMAKE_TOOLCHAIN_FILE=${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake \
            -DVCPKG_TARGET_TRIPLET=arm64-linux-dynamic-release \
            -DVCPKG_INSTALLED_DIR=${VCPKG_ROOT}/vcpkg_installed \
            -DBUILD_SHARED_LIBS=ON \
            -DCMAKE_BUILD_TYPE=Release \
            -DBUILD_FOR_ARM64=ON &&
            cmake --build build -j$(nproc);
        fi""",
    ]

    try:
        # Run without capturing output so the user can see progress
        console.print("[blue]Running build command...[/blue]")
        subprocess.run(build_cmd, check=True, cwd=app_dir)

        # Check if build succeeded
        for path in binary_paths:
            if os.path.exists(path):
                console.print(f"[green]Successfully built binary at: {path}[/green]")
                return True

        # If we get here, the build might have succeeded but we can't find the binary
        console.print(
            "[bold yellow]Warning: Build completed but binary not found in expected locations.[/bold yellow]"
        )
        # Try to find it manually
        binary_path = subprocess.run(
            ["find", app_dir, "-type", "f", "-name", app_name, "-not", "-path", "*/.*"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()

        if binary_path:
            binary_path = binary_path.split("\n")[0]  # Take the first match if multiple
            console.print(f"[green]Found binary at: {binary_path}[/green]")

            # Try to copy it to one of the standard locations
            build_dir = os.path.join(app_dir, "build")
            os.makedirs(build_dir, exist_ok=True)
            shutil.copy(binary_path, os.path.join(build_dir, app_name))
            console.print(
                f"[green]Copied binary to: {os.path.join(build_dir, app_name)}[/green]"
            )
            return True

        return False
    except subprocess.CalledProcessError:
        console.print(
            "[bold red]Error:[/bold red] Failed to build application. Check the CMake output above for details."
        )
        return False


def deploy_cmd(args):
    """Handle the deploy command"""
    # Ensure Docker is available and running
    if not ensure_docker():
        return

    # Get absolute path of app directory
    app_dir = os.path.abspath(args.app_dir)

    # Validate manifest.json
    manifest_path = os.path.join(app_dir, "manifest.json")
    manifest = validate_manifest(manifest_path)
    if not manifest:
        return

    # Get app name from manifest
    app_name = manifest["name"]
    console.print(f"[bold]Deploying application:[/bold] [yellow]{app_name}[/yellow]")

    # First, build the app
    if not build_app(app_dir, app_name):
        console.print("[bold red]Error:[/bold red] Failed to build the application.")
        return

    # Package the app
    if not package_app(app_dir, app_name):
        return

    # Find the generated .deb package
    deb_package = find_deb_package(app_dir)
    if not deb_package:
        return

    # Deploy the package to the device
    uri = args.uri
    print(f"Deploying package to: {uri}")
    if uri:
        deploy_package(uri, deb_package)
    else:
        console.print(
            "[yellow]No URI provided. Package created but not deployed.[/yellow]"
        )
        console.print(f"[green]Package available at:[/green] {deb_package}")


def add_commands(subparsers):
    """Add deploy commands to the CLI"""
    deploy_parser = subparsers.add_parser(
        "deploy", help="Deploy an application to a Synapse device"
    )
    deploy_parser.add_argument(
        "app_dir", nargs="?", default=".", help="Path to the application directory"
    )
    deploy_parser.set_defaults(func=deploy_cmd)


def detect_arch() -> str:
    """Return an architecture tag suffix (``arm64`` or ``amd64``)."""
    arch = subprocess.check_output(["uname", "-m"]).decode("utf-8").strip()
    return "arm64" if arch in ("arm64", "aarch64") else "amd64"


def ensure_docker() -> bool:
    """Return True if the *docker* CLI is available and the daemon responds.

    Prints a clear, user-friendly message and returns ``False`` otherwise so the
    caller can abort early.
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
    """Build (or rebuild) the SDK Docker image used for cross-compiling *app_name*.

    Returns the fully-qualified image tag (``<app>:latest-<arch>``) or raises
    ``subprocess.CalledProcessError`` if the build fails.
    """
    if app_name is None:
        app_name = os.path.basename(app_dir)

    arch_suffix = detect_arch()  # "arm64" or "amd64"

    # Pick an arch-specific Dockerfile if it exists, otherwise fall back to the
    # generic one.
    dockerfile_rel = (
        f"ops/docker/Dockerfile.{arch_suffix}"
        if arch_suffix == "arm64"
        else "ops/docker/Dockerfile"
    )
    dockerfile_path = os.path.join(app_dir, dockerfile_rel)
    if not os.path.exists(dockerfile_path):
        # Last chance: fall back to the generic Dockerfile regardless of arch.
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
