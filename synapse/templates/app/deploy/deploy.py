#!/usr/bin/env python3

import os
import sys
import getpass
import paramiko
import json
import base64
import time
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich import box

# Initialize Rich console
console = Console()

# Configuration
CACHE_FILE = ".synapse_deploy_cache.json"

def get_credentials():
    """Prompt for device credentials with rich formatting"""
    console.print("[bold yellow]Device Connection Details[/bold yellow]")
    ip_address = Prompt.ask("Enter SciFi device IP address")
    username = Prompt.ask("Enter login username", default="scifi")
    login_password = getpass.getpass("Enter login password: ")
    root_password = getpass.getpass("Enter root password for package installation: ")
    return ip_address, username, login_password, root_password

def load_cached_credentials():
    """Load cached credentials if they exist"""
    try:
        if os.path.exists(CACHE_FILE):
            with console.status("[bold blue]Loading cached credentials...[/bold blue]"):
                with open(CACHE_FILE, 'r') as f:
                    data = json.load(f)
                    ip_address = data.get('ip_address')
                    username = data.get('username', 'admin')
                    encoded_login_password = data.get('encoded_login_password')
                    encoded_root_password = data.get('encoded_root_password')
                    
                    if encoded_login_password and encoded_root_password:
                        login_password = base64.b64decode(encoded_login_password).decode('utf-8')
                        root_password = base64.b64decode(encoded_root_password).decode('utf-8')
                        console.print(f"[green]Using cached credentials for [bold]{username}@{ip_address}[/bold][/green]")
                        return ip_address, username, login_password, root_password
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to load cached credentials: {e}[/yellow]")
    return None, None, None, None

def save_credentials(ip_address, username, login_password, root_password):
    """Save credentials to cache file"""
    try:
        with console.status("[bold blue]Saving credentials...[/bold blue]"):
            with open(CACHE_FILE, 'w') as f:
                data = {
                    'ip_address': ip_address,
                    'username': username,
                    'encoded_login_password': base64.b64encode(login_password.encode('utf-8')).decode('utf-8'),
                    'encoded_root_password': base64.b64encode(root_password.encode('utf-8')).decode('utf-8')
                }
                json.dump(data, f)
            os.chmod(CACHE_FILE, 0o600)  # Restrict file permissions
            console.print("[green]Credentials saved successfully[/green]")
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to save credentials: {e}[/yellow]")

def deploy_package(ip_address, username, login_password, root_password, deb_package):
    """Deploy and install the deb package to the SciFi device"""
    package_filename = os.path.basename(deb_package)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}[/bold blue]"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        # Setup overall task
        overall_task = progress.add_task("[yellow]Overall deployment progress...", total=4)
        
        # Connect to device
        connect_task = progress.add_task(f"[green]Connecting as {username}@{ip_address}...", total=1)
        try:
            # Create SSH client
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Connect to the device
            client.connect(ip_address, username=username, password=login_password, timeout=10)
            progress.update(connect_task, advance=1)
            progress.update(overall_task, advance=1)
            
            # Create SFTP task
            transfer_task = progress.add_task(f"[cyan]Transferring {package_filename}...", total=1)
            
            # Create SFTP client
            sftp = client.open_sftp()
            remote_path = f"/tmp/{package_filename}"
            
            # Upload the package
            sftp.put(deb_package, remote_path)
            progress.update(transfer_task, advance=1)
            progress.update(overall_task, advance=1)
            
            # Install task
            install_task = progress.add_task("[magenta]Installing package with root privileges...", total=1)
            
            # Use expect-like behavior with Paramiko to handle su
            # First, we create an interactive shell session
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
            time.sleep(3)  # Give dpkg time to run
            
            # Exit from root shell
            shell.send("exit\n")
            time.sleep(0.5)
            
            # Collect the final output
            while shell.recv_ready():
                chunk = shell.recv(4096).decode('utf-8')
                output += chunk
            
            # Check for common error indicators
            if "error" in output.lower() or "failed" in output.lower():
                progress.update(install_task, completed=1, visible=False)
                progress.update(overall_task, visible=False)
                console.print(Panel(
                    f"[bold red]Installation Error[/bold red]\n\n{output}",
                    title="Deployment Failed",
                    border_style="red",
                    box=box.DOUBLE
                ))
                return False
            
            # Complete the tasks
            progress.update(install_task, advance=1)
            progress.update(overall_task, advance=1)
            
            # Cleanup task
            cleanup_task = progress.add_task("[blue]Cleaning up...", total=1)
            shell.send(f"rm {remote_path}\n")
            time.sleep(0.5)
            progress.update(cleanup_task, advance=1)
            progress.update(overall_task, advance=1)
            
            console.print(Panel(
                f"[bold green]Successfully deployed[/bold green] [yellow]{package_filename}[/yellow] [bold green]to[/bold green] [blue]{ip_address}[/blue]",
                title="Deployment Successful",
                border_style="green",
                box=box.DOUBLE
            ))
            return True
            
        except Exception as e:
            progress.update(overall_task, visible=False)
            console.print(Panel(
                f"[bold red]Connection Error[/bold red]\n\n{str(e)}",
                title="Deployment Failed",
                border_style="red",
                box=box.DOUBLE
            ))
            return False
        finally:
            try:
                if 'shell' in locals():
                    shell.close()
                if 'sftp' in locals():
                    sftp.close()
                if 'client' in locals():
                    client.close()
            except:
                pass

def main():
    # Print welcome banner
    console.print(Panel(
        "[bold]Synapse App Deployment Tool[/bold]",
        border_style="blue",
        box=box.ROUNDED
    ))
    
    # Check if a .deb package was provided
    if len(sys.argv) < 2:
        console.print("[bold red]Error:[/bold red] No .deb package specified.")
        console.print(f"Usage: {sys.argv[0]} path/to/package.deb")
        sys.exit(1)
    
    deb_package = sys.argv[1]
    
    # Check if the IP address was provided as a second argument
    ip_address = None
    if len(sys.argv) > 2:
        ip_address = sys.argv[2]
    
    # Check if the .deb package exists
    if not os.path.isfile(deb_package):
        console.print(f"[bold red]Error:[/bold red] The specified .deb package does not exist: [yellow]{deb_package}[/yellow]")
        sys.exit(1)
    
    # Show package info
    package_size = os.path.getsize(deb_package) / (1024 * 1024)  # Size in MB
    console.print(f"[bold cyan]Package:[/bold cyan] [yellow]{os.path.basename(deb_package)}[/yellow] ([cyan]{package_size:.2f} MB[/cyan])")
    
    # Load cached credentials or use provided IP
    username = None
    login_password = None
    root_password = None
    
    if ip_address is None:
        ip_address, username, login_password, root_password = load_cached_credentials()
    
    # If no cached credentials or IP was provided but no credentials, prompt for them
    if not ip_address or not username or not login_password or not root_password:
        if ip_address:
            console.print(f"[bold]Using target device:[/bold] [yellow]{ip_address}[/yellow]")
            username = Prompt.ask("Enter login username", default="scifi")
            login_password = getpass.getpass("Enter login password: ")
            root_password = getpass.getpass("Enter root password for package installation: ")
        else:
            ip_address, username, login_password, root_password = get_credentials()
    
    # Try to deploy until successful
    while True:
        if deploy_package(ip_address, username, login_password, root_password, deb_package):
            # Save successful credentials
            save_credentials(ip_address, username, login_password, root_password)
            break
        else:
            if Confirm.ask("[yellow]Would you like to retry with different credentials?[/yellow]"):
                ip_address, username, login_password, root_password = get_credentials()
            else:
                console.print("[bold red]Deployment aborted by user.[/bold red]")
                sys.exit(1)

if __name__ == "__main__":
    main() 