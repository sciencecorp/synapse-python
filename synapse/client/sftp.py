import getpass
import logging
import os
import socket
from typing import Optional

import paramiko
import paramiko.ssh_exception
import yaml
from rich.console import Console
from rich.prompt import Confirm

def connect_sftp(hostname, username, password=None, pass_filename=None, key_filename=None, port=22):
    """
    Connect to SFTP server and return SFTP client object
    
    Args:
        hostname: SFTP server hostname or IP
        username: Username for authentication
        password: Password for authentication (optional if using key)
        key_filename: Path to private key file (optional if using password)
        port: SFTP server port (default: 22)
        
    Returns:
        tuple: (SSHClient, SFTPClient) - Keep both to properly close connection
    """
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if pass_filename is not None:
        try:
            with open(pass_filename, "r") as f:
                password = f.read().strip()
        except Exception as e:
            logging.error(f"Failed to read password file: {e}")
            return None, None
    try:
        ssh.connect(
            hostname=hostname,
            port=port,
            username=username,
            password=password,
            key_filename=key_filename,
            timeout=10,
            allow_agent=False,
            look_for_keys=False,
        )
        sftp = ssh.open_sftp()
    except TimeoutError as e:
        logging.error(f"Connection to {hostname} timed out")
        return None, None
    except socket.error as e:
        logging.error(f"Socket error connecting to {hostname}:{port}: {e}")
        return None, None
    except paramiko.ssh_exception.SSHException as e:
        logging.error(f"SSH error connecting to {hostname}:{port}: {e}")
        raise  # Re-raise to let caller handle it

    return ssh, sftp

def close_sftp(ssh, sftp):
    """
    Close SFTP connection
    
    Args:
        ssh: SSHClient object
        sftp: SFTPClient object
    """
    if sftp is not None:
        sftp.close()
    if ssh is not None:
        ssh.close()

# --- SFTP connection and password handling ---------------------------------
#
# Moved here from synapse/cli/files.py when `synapsectl file` switched to gRPC.
# deploy_model is the last SFTP consumer, so this lives beside the SFTP client
# rather than in a CLI module that no longer speaks SFTP at all. When
# deploy_model moves to WriteFile, all of this goes with it -- along with the
# separate SFTP password.

SCIFI_DEFAULT_SFTP_USER = "scifi-sftp"
DEFAULT_ENV_FILE = ".scienv"

def setup_connection(
    uri: str,
    username: str,
    env_file: str,
    forget_password: bool,
    console: Console,
) -> Optional[tuple[paramiko.SSHClient, paramiko.SFTPClient]]:
    dev_name = Device(uri).get_name()
    password = find_password(
        dev_name, env_file
    )  # Check if password is provided or stored in env file
    if password is None:
        console.print(f"[bold red]Didnt find any password for {uri}[/bold red]")
        return

    # Open SFTP connection
    with console.status("Connecting to Synapse device...", spinner="bouncingBall"):
        try:
            ssh, sftp_conn = sftp.connect_sftp(uri, username, password)
        except paramiko.ssh_exception.AuthenticationException:
            console.print(f"[bold red]Authentication failed for {uri}[/bold red]")
            console.print("[yellow] Incorrect username or password.")
            return None
    if ssh is None or sftp_conn is None:
        console.print(f"[bold red]Failed to connect to {uri}[/bold red]")
        return
    # If the connection is successful, we can prompt the user if they want to save the password
    if not forget_password and dev_name is not None:
        save_password(password, env_file, dev_name)
    return ssh, sftp_conn

def find_password(dev_name: Optional[str], env_file: Optional[str]):
    password = None
    if env_file is not None and dev_name is not None:
        if os.path.exists(env_file):
            password = load_pass_from_env_file(env_file, dev_name)
            if password is not None:
                return password
    password = getpass.getpass("Enter password: ")
    return password

def save_password(password: str, env_file: str, device_name: str):
    if env_file is None or device_name is None or password is None:
        return
    if os.path.exists(env_file):
        if load_pass_from_env_file(env_file, device_name) is not None:
            return

    save_pass = Confirm.ask(f"Save password for {device_name} in {env_file}?")
    if not save_pass:
        return
    store_pass_to_env_file(env_file, device_name, password)

def load_pass_from_env_file(env_file: str, device_name: str) -> Optional[str]:
    try:
        with open(env_file, "r") as f:
            env_loaded = yaml.safe_load(f)
            if env_loaded is None:
                return None
            if "sftp_passwords" not in env_loaded:
                return None
            passwords = env_loaded.get("sftp_passwords", {})
            if device_name in passwords:
                try:
                    stored_pass = passwords[device_name]
                    return stored_pass
                except Exception:
                    print(
                        f"Couldnt read password for {device_name} from env file. Env file may be improperly formatted."
                    )
                    return None
            else:
                return None
    except Exception as e:
        print(f"Couldnt read env file at: {env_file}. {e}")
    return None


# Store password to the .env file in yaml format

def store_pass_to_env_file(env_file: str, device_name: str, password: str):
    try:
        prev_env = {}
        if os.path.exists(env_file):
            with open(env_file, "r") as f:
                prev_env = yaml.safe_load(f)
                prev_env = prev_env if prev_env is not None else {}
        passwords = prev_env.get("sftp_passwords", {})
        passwords[device_name] = password
        prev_env["sftp_passwords"] = passwords
        with open(env_file, "w", encoding="utf8") as f:
            yaml.dump(prev_env, f, default_flow_style=False)
    except TypeError:
        print(
            f"Failed to store pass to env file at: {env_file}. Env file may be improperly formatted."
        )
    except Exception as e:
        print(f"Failed to store pass to env file at: {env_file}. {e}")
