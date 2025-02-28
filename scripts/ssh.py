"""
Module for handling SSH connections and remote command execution.
"""

import os
import time
import paramiko
from typing import List, Dict, Any, Optional, Tuple, Union

class SSHClient:
    """
    SSH client for executing commands on remote hosts.
    """
    
    def __init__(
        self,
        host: str,
        username: str,
        port: int = 22,
        private_key_path: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 60,
    ):
        """
        Initialize a new SSH client.
        
        Args:
            host: Remote host IP or hostname
            username: SSH username
            port: SSH port
            private_key_path: Path to private key file (if using key-based auth)
            password: Password (if using password auth)
            timeout: Connection timeout in seconds
        """
        self.host = host
        self.username = username
        self.port = port
        self.private_key_path = private_key_path
        self.password = password
        self.timeout = timeout
        self.client = None
    
    def connect(self, retry_attempts: int = 10, retry_delay: int = 5) -> bool:
        """
        Connect to the remote host.
        
        Args:
            retry_attempts: Number of connection retry attempts
            retry_delay: Delay between retries in seconds
            
        Returns:
            bool: True if connection successful, False otherwise
        """
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        for attempt in range(retry_attempts):
            try:
                if self.private_key_path:
                    key = paramiko.RSAKey.from_private_key_file(os.path.expanduser(self.private_key_path))
                    self.client.connect(
                        hostname=self.host,
                        port=self.port,
                        username=self.username,
                        pkey=key,
                        timeout=self.timeout,
                    )
                else:
                    self.client.connect(
                        hostname=self.host,
                        port=self.port,
                        username=self.username,
                        password=self.password,
                        timeout=self.timeout,
                    )
                return True
            except Exception as e:
                if attempt < retry_attempts - 1:
                    print(f"Connection attempt {attempt + 1} failed: {str(e)}. Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    print(f"Failed to connect after {retry_attempts} attempts: {str(e)}")
                    return False
        return False
    
    def disconnect(self):
        """Close the SSH connection."""
        if self.client:
            self.client.close()
            self.client = None
    
    def execute_command(self, command: str, get_pty: bool = False) -> Tuple[int, str, str]:
        """
        Execute a command on the remote host.
        
        Args:
            command: The command to execute
            get_pty: Whether to request a pseudo-terminal
            
        Returns:
            Tuple[int, str, str]: (exit code, stdout, stderr)
        """
        if not self.client:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            stdin, stdout, stderr = self.client.exec_command(command, get_pty=get_pty)
            exit_code = stdout.channel.recv_exit_status()
            stdout_str = stdout.read().decode('utf-8')
            stderr_str = stderr.read().decode('utf-8')
            return exit_code, stdout_str, stderr_str
        except Exception as e:
            return -1, "", str(e)
    
    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """
        Upload a file to the remote host.
        
        Args:
            local_path: Path to local file
            remote_path: Destination path on remote host
            
        Returns:
            bool: True if upload successful, False otherwise
        """
        if not self.client:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            sftp = self.client.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()
            return True
        except Exception as e:
            print(f"Failed to upload file: {str(e)}")
            return False

    def download_file(self, remote_path: str, local_path: str) -> bool:
        """
        Download a file from the remote host.
        
        Args:
            remote_path: Path to file on remote host
            local_path: Destination path on local machine
            
        Returns:
            bool: True if download successful, False otherwise
        """
        if not self.client:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            sftp = self.client.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()
            return True
        except Exception as e:
            print(f"Failed to download file: {str(e)}")
            return False 