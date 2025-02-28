"""
Module for provisioning a VM with default software.
"""

from typing import List, Dict, Any, Optional
from scripts.ssh import SSHClient

class VMProvisioner:
    """
    Provision a VM with default software and configurations.
    """
    
    def __init__(self, ssh_client: SSHClient):
        """
        Initialize a new VMProvisioner.
        
        Args:
            ssh_client: SSHClient instance for remote command execution
        """
        self.ssh = ssh_client
    
    def provision(self, packages: List[str] = None) -> bool:
        """
        Provision the VM with updates and specified packages.
        
        Args:
            packages: List of packages to install (default: basic utils)
            
        Returns:
            bool: True if provisioning successful, False otherwise
        """
        if packages is None:
            packages = [
                "vim",
                "curl",
                "wget",
                "git",
                "htop",
                "net-tools",
                "unzip",
                "jq",
            ]
        
        print("Updating package lists...")
        exit_code, _, stderr = self.ssh.execute_command("sudo apt-get update")
        if exit_code != 0:
            print(f"Failed to update package lists: {stderr}")
            return False
        
        print("Upgrading packages...")
        exit_code, _, stderr = self.ssh.execute_command("sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y")
        if exit_code != 0:
            print(f"Failed to upgrade packages: {stderr}")
            return False
        
        print(f"Installing packages: {', '.join(packages)}")
        exit_code, _, stderr = self.ssh.execute_command(f"sudo DEBIAN_FRONTEND=noninteractive apt-get install -y {' '.join(packages)}")
        if exit_code != 0:
            print(f"Failed to install packages: {stderr}")
            return False
        
        # Configure timezone
        self.ssh.execute_command("sudo timedatectl set-timezone UTC")
        
        # Configure locale
        self.ssh.execute_command("sudo locale-gen en_US.UTF-8")
        self.ssh.execute_command("sudo update-locale LANG=en_US.UTF-8")
        
        # Set up swap if not using cloud-init (cloud-init may configure swap)
        self._configure_swap()
        
        # Secure sshd config
        self._secure_ssh()
        
        # Set up firewall
        self._configure_firewall()
        
        print("VM provisioning completed successfully")
        return True
    
    def _configure_swap(self, size_mb: int = 2048) -> None:
        """Configure swap space."""
        # Check if swap already exists
        exit_code, swap_info, _ = self.ssh.execute_command("swapon --show")
        if exit_code == 0 and swap_info.strip():
            print("Swap is already configured, skipping")
            return
        
        print(f"Setting up {size_mb}MB swap file...")
        
        # Create and configure swap file
        self.ssh.execute_command(f"sudo fallocate -l {size_mb}M /swapfile")
        self.ssh.execute_command("sudo chmod 600 /swapfile")
        self.ssh.execute_command("sudo mkswap /swapfile")
        self.ssh.execute_command("sudo swapon /swapfile")
        
        # Make swap permanent
        self.ssh.execute_command('echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab')
        
        # Configure swappiness
        self.ssh.execute_command("echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf")
        self.ssh.execute_command("sudo sysctl -p")
    
    def _secure_ssh(self) -> None:
        """Secure SSH configuration."""
        config_lines = [
            "PermitRootLogin no",
            "PasswordAuthentication no",
            "X11Forwarding no",
            "MaxAuthTries 5",
            "ClientAliveInterval 300",
            "ClientAliveCountMax 2",
        ]
        
        print("Securing SSH configuration...")
        
        # Create a temporary file with the new settings
        config_content = "\n".join(config_lines)
        self.ssh.execute_command(f"echo '{config_content}' > /tmp/sshd_config_extra")
        
        # Append to the existing config if the lines don't already exist
        for line in config_lines:
            key = line.split()[0]
            self.ssh.execute_command(f"grep -q '{key}' /etc/ssh/sshd_config || echo '{line}' | sudo tee -a /etc/ssh/sshd_config")
        
        # Clean up and restart sshd
        self.ssh.execute_command("rm /tmp/sshd_config_extra")
        self.ssh.execute_command("sudo systemctl restart sshd")
    
    def _configure_firewall(self) -> None:
        """Configure UFW firewall."""
        print("Configuring firewall...")
        
        # Install UFW if not already installed
        self.ssh.execute_command("sudo apt-get install -y ufw")
        
        # Configure firewall rules
        self.ssh.execute_command("sudo ufw default deny incoming")
        self.ssh.execute_command("sudo ufw default allow outgoing")
        self.ssh.execute_command("sudo ufw allow ssh")
        
        # Allow k3s ports
        self.ssh.execute_command("sudo ufw allow 6443/tcp")  # Kubernetes API server
        self.ssh.execute_command("sudo ufw allow 8472/udp")  # Flannel VXLAN
        self.ssh.execute_command("sudo ufw allow 10250/tcp")  # Kubelet
        
        # Enable firewall (don't wait for the command to complete)
        self.ssh.execute_command("sudo ufw --force enable", get_pty=True) 