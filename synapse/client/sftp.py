import logging
import paramiko
import paramiko.ssh_exception

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
            timeout=5
        )
        sftp = ssh.open_sftp()
    except TimeoutError as e:
        logging.error(f"Connection to {hostname} timed out")
        return None, None
    
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
