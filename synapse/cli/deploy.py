import json
import os

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt

import synapse.client.sftp as sftp
from synapse.cli import build as builder

console = Console()
log_console = Console(stderr=True)


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


def deploy_cmd(args):
    """Handle the deploy command"""
    # If user supplied a pre-built package, skip local build/pkg steps.
    if args.package:
        deb_package = os.path.abspath(args.package)
        if not os.path.exists(deb_package):
            console.print(
                f"[bold red]Error:[/bold red] Provided package not found: {deb_package}"
            )
            return

        console.print(
            f"[bold]Deploying pre-built package:[/bold] [yellow]{os.path.basename(deb_package)}[/yellow]"
        )

    else:
        # Ensure Docker is available and running only when we need to build
        if not builder.ensure_docker():
            return

        # Get absolute path of app directory
        app_dir = os.path.abspath(args.app_dir)

        # Validate manifest.json
        manifest_path = os.path.join(app_dir, "manifest.json")
        manifest = builder.validate_manifest(manifest_path)
        if not manifest:
            return

        # Get app name from manifest
        app_name = manifest["name"]
        console.print(
            f"[bold]Deploying application:[/bold] [yellow]{app_name}[/yellow]"
        )

        # Build & package locally
        if not builder.build_app(app_dir, app_name):
            console.print(
                "[bold red]Error:[/bold red] Failed to build the application."
            )
            return

        if not builder.package_app(app_dir, app_name):
            return

        deb_package = builder.find_deb_package(app_dir)
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
    deploy_parser.add_argument(
        "--package",
        "-p",
        help="Path to a pre-built .deb to deploy (skips local build and package steps)",
        type=str,
        default=None,
    )
    deploy_parser.set_defaults(func=deploy_cmd)
