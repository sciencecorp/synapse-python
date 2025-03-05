import logging
import paramiko
import paramiko.ssh_exception

def connect_sftp(hostname, username, password=None, key_filename=None, port=22):
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
    
    try: 
        ssh.connect(
            hostname=hostname,
            port=port,
            username=username,
            password=password,
            key_filename=key_filename,
            timeout=5
        )
    except TimeoutError as e:
        logging.error(f"Connection to {hostname} timed out")
        return None, None
    except paramiko.ssh_exception.SSHException as e:
        logging.error(f"Failed to connect to {hostname}: {e}")
        return None, None
    
    sftp = ssh.open_sftp()
    return ssh, sftp

def close_sftp(ssh, sftp):
    """
    Close SFTP connection
    
    Args:
        ssh: SSHClient object
        sftp: SFTPClient object
    """
    sftp.close()
    ssh.close()