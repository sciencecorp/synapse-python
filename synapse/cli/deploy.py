import os
import subprocess
import shutil
import json
import time
import logging
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
)
from rich.prompt import Prompt
from rich import box

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


def package_app(app_dir, app_name):
    """Package the application into a .deb file"""
    # Check if we're in a Docker container
    if os.path.exists("/.dockerenv"):
        # We're inside Docker, directly run the package script
        package_script = os.path.join(app_dir, "ops", "package", "package.sh")
        if not os.path.exists(package_script):
            console.print(
                f"[bold red]Error:[/bold red] Package script not found at {package_script}"
            )
            return False

        # Make sure the script is executable
        os.chmod(package_script, 0o755)

        # Make sure all the other scripts are executable too
        script_dir = os.path.join(app_dir, "ops", "package", "scripts")
        if os.path.exists(script_dir):
            for script in os.listdir(script_dir):
                if script.endswith(".sh"):
                    script_path = os.path.join(script_dir, script)
                    os.chmod(script_path, 0o755)

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}[/bold blue]"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[yellow]Packaging application...", total=1)

            # Run the package script
            try:
                subprocess.run(["bash", package_script], check=True, cwd=app_dir)
                progress.update(task, advance=1)
                return True
            except subprocess.CalledProcessError as e:
                console.print(
                    f"[bold red]Error:[/bold red] Failed to package application: {e}"
                )
                return False
    else:
        # We're outside Docker, need to use docker to package
        # Always use the build_docker.sh from the synapse-python package directly
        build_docker_script = get_build_docker_script()

        if not os.path.exists(build_docker_script):
            console.print(
                f"[bold red]Error:[/bold red] Could not find Docker build script at {build_docker_script}"
            )
            return False

        # Make sure the script is executable
        os.chmod(build_docker_script, 0o755)

        # Path to ops templates inside synapse-python
        template_ops_dir = get_template_ops_dir()

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}[/bold blue]"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            build_task = progress.add_task("[yellow]Building Docker image...", total=1)

            # ------------------------------------------------------------------
            # STEP 1: Build the Docker image used for packaging the application
            # ------------------------------------------------------------------
            try:
                result = subprocess.run(
                    ["bash", build_docker_script],
                    check=True,
                    cwd=app_dir,
                    capture_output=True,
                    text=True,
                )

                # Log any warnings emitted by the build step so they are not lost
                if result.stderr and any(
                    word in result.stderr.lower() for word in ("error", "fail")
                ):
                    console.print(f"[bold red]Warning:[/bold red] {result.stderr}")

                # Mark the *build* step as complete
                progress.update(build_task, advance=1)
            except subprocess.CalledProcessError as exc:
                console.print(
                    f"[bold red]Error:[/bold red] Failed to build Docker image: {exc}"
                )
                if exc.stderr:
                    console.print(f"[red]{exc.stderr}[/red]")
                return False

            # ------------------------------------------------------------------
            # STEP 2: Package the application inside the freshly-built container
            # ------------------------------------------------------------------
            package_task = progress.add_task(
                "[yellow]Packaging application...", total=1
            )

            tag_suffix = detect_arch()
            image = f"{os.path.basename(app_dir)}:latest-{tag_suffix}"

            # Ensure the helper script exists and is executable on the host so it
            # can be executed inside the container.
            prepare_script = os.path.join(template_ops_dir, "prepare_and_package.sh")
            if not os.path.exists(prepare_script):
                console.print(
                    f"[bold red]Error:[/bold red] Helper script not found at {prepare_script}"
                )
                return False

            # Make sure the script has execute permissions (mostly relevant for
            # Windows or freshly-cloned repos).
            os.chmod(prepare_script, 0o755)

            cmd = [
                "docker",
                "run",
                "-i",
                "--rm",
                "-v",
                f"{os.path.abspath(app_dir)}:/home/workspace",
                "-v",
                f"{template_ops_dir}:/synapse_ops:ro",
                image,
                "/bin/bash",
                "/synapse_ops/prepare_and_package.sh",
                app_name,
            ]

            # Run the packaging script in Docker - capture output
            print(f"Running packaging script in Docker: {image}")
            try:
                # Capture output to prevent it from interfering with progress bars
                result = subprocess.run(
                    cmd, check=True, cwd=app_dir, capture_output=True, text=True
                )

                # Only log errors if they occur
                if result.stderr and (
                    "error" in result.stderr.lower() or "fail" in result.stderr.lower()
                ):
                    console.print(f"[bold red]Warning:[/bold red] {result.stderr}")

                progress.update(package_task, advance=1)

                # Display success message after completion
                console.print("[green]Package created successfully![/green]")
                return True
            except subprocess.CalledProcessError as e:
                console.print(
                    f"[bold red]Error:[/bold red] Failed to package application: {e}"
                )
                if e.stderr:
                    console.print(f"[red]{e.stderr}[/red]")
                return False


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

    # Stop any previous progress display
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
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        deploy_task = progress.add_task(
            f"[yellow]Deploying to {ip_address}...", total=3
        )

        try:
            # Deploy directly using paramiko
            client = None
            sftp = None
            shell = None

            # Create SSH client
            import paramiko

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Connect to the device (connection task)
            connect_task = progress.add_task("[green]Connecting to device...", total=1)

            try:
                client.connect(
                    ip_address, username=username, password=login_password, timeout=10
                )
                progress.update(connect_task, completed=1)
                progress.update(deploy_task, advance=1)
            except Exception as e:
                progress.update(connect_task, visible=False)
                console.print(
                    f"[bold red]Error connecting to {ip_address}:[/bold red] {str(e)}"
                )
                console.print(
                    "[yellow]Please check your username and password.[/yellow]"
                )
                return False

            # Upload file task
            upload_task = progress.add_task("[cyan]Uploading package...", total=1)

            try:
                # Create SFTP client and upload
                sftp = client.open_sftp()
                remote_path = f"/tmp/{package_filename}"
                sftp.put(deb_package_path, remote_path)
                progress.update(upload_task, completed=1)
                progress.update(deploy_task, advance=1)
            except Exception as e:
                progress.update(upload_task, visible=False)
                console.print(f"[bold red]Error uploading package:[/bold red] {str(e)}")
                return False

            # Install task
            install_task = progress.add_task("[magenta]Installing package...", total=1)

            try:
                # Use expect-like behavior with Paramiko to handle su
                shell = client.invoke_shell()

                # Set up a way to collect output
                output = ""

                # Send su command
                shell.send("su -\n")
                time.sleep(1)  # Wait for password prompt

                # Send root password
                shell.send(f"{root_password}\n")
                time.sleep(1)  # Wait for su to authenticate

                # Send dpkg command
                shell.send(f"dpkg -i {remote_path}\n")
                time.sleep(5)  # Give dpkg time to run

                # Exit from root shell
                shell.send("exit\n")
                time.sleep(0.5)

                # Collect the final output
                while shell.recv_ready():
                    chunk = shell.recv(4096).decode("utf-8")
                    output += chunk

                # Check for common error indicators
                if "error" in output.lower() or "failed" in output.lower():
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

                # Cleanup
                shell.send(f"rm {remote_path}\n")
                time.sleep(0.5)

                # Mark installation as complete
                progress.update(install_task, completed=1)
                progress.update(deploy_task, advance=1)

                # Save successful credentials
                save_credentials(ip_address, username, login_password, root_password)

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
                if shell:
                    shell.close()
                if sftp:
                    sftp.close()
                if client:
                    client.close()
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

    # Always use the shared build_docker.sh script
    build_docker_script = get_build_docker_script()

    if not os.path.exists(build_docker_script):
        console.print(
            f"[bold red]Error:[/bold red] Could not find Docker build script at {build_docker_script}"
        )
        return False

    # Make sure the script is executable
    os.chmod(build_docker_script, 0o755)

    try:
        # Run the build script without capturing output so user can see progress
        console.print("[blue]Running build_docker.sh...[/blue]")
        subprocess.run(["bash", build_docker_script], check=True, cwd=app_dir)
        console.print("[green]Successfully built Docker image.[/green]")
    except subprocess.CalledProcessError as e:
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
    # Deploy command
    deploy_parser = subparsers.add_parser(
        "deploy", help="Deploy an application to a Synapse device"
    )
    deploy_parser.add_argument(
        "app_dir", nargs="?", default=".", help="Path to the application directory"
    )
    deploy_parser.set_defaults(func=deploy_cmd)


# ---------------------------------------------------------------------------
# Helper utilities shared across this module
# ---------------------------------------------------------------------------


def get_synapse_root() -> str:
    """Return the absolute path to the *synapse-python* repository root."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(script_dir, "..", ".."))


def get_build_docker_script() -> str:
    """Return the canonical *build_docker.sh* path used throughout the tool."""
    return os.path.join(
        get_synapse_root(), "synapse", "templates", "app", "build_docker.sh"
    )


def get_template_ops_dir() -> str:
    """Return the path to the shared *ops* template directory."""
    return os.path.join(get_synapse_root(), "synapse", "templates", "app", "ops")


def detect_arch() -> str:
    """Return an architecture tag suffix (``arm64`` or ``amd64``)."""
    arch = subprocess.check_output(["uname", "-m"]).decode("utf-8").strip()
    return "arm64" if arch in ("arm64", "aarch64") else "amd64"


# ---------------------------------------------------------------------------
# Environment sanity-check helpers
# ---------------------------------------------------------------------------


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
