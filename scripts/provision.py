"""
Module for provisioning a VM with default software.
"""

from typing import List, Dict, Any, Optional
from scripts.ssh import SSHClient
import os
import time

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
        self.vm = None  # Reference to ProxmoxVM instance (if available)
    
    def set_vm(self, vm):
        """
        Set a reference to the ProxmoxVM instance.
        This allows the provisioner to inform the VM when the guest agent is installed.
        
        Args:
            vm: ProxmoxVM instance
        """
        self.vm = vm
    
    def provision(self, admin_username: Optional[str] = None, admin_password: Optional[str] = None, admin_ssh_key: Optional[str] = None) -> bool:
        """
        Provision a VM with default software.
        
        Args:
            admin_username: Username for the new admin user (optional)
            admin_password: Password for the new admin user (optional)
            admin_ssh_key: SSH public key for the new admin user (optional, path or content)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if we can import the read_ssh_key_if_path function
            try:
                # Try to import the function from __main__
                import sys
                main_module = sys.modules.get('__main__')
                if main_module and hasattr(main_module, 'read_ssh_key_if_path'):
                    read_ssh_key_fn = main_module.read_ssh_key_if_path
                    # If the admin_ssh_key looks like a file path, read it
                    if admin_ssh_key:
                        admin_ssh_key = read_ssh_key_fn(admin_ssh_key)
                        print(f"Using admin SSH key: {admin_ssh_key[:20]}..." if admin_ssh_key else "None")
            except ImportError:
                # If we can't import it, just use the key as-is
                if admin_ssh_key and (admin_ssh_key.startswith('/') or admin_ssh_key.startswith('~')):
                    print(f"Warning: admin_ssh_key looks like a file path. If intended as a path, use the SSH key content instead.")
            
            # Update system packages
            if not self._update_packages():
                return False
            
            # Install essential packages
            if not self._install_essentials():
                return False
            
            # Create admin user if specified
            if admin_username:
                if not self._create_admin_user(admin_username, admin_password, admin_ssh_key):
                    return False
            
            # Set up QEMU Guest Agent
            if not self._install_qemu_agent():
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
        except Exception as e:
            print(f"Failed to provision VM: {e}")
            return False
    
    def _create_admin_user(self, username: str, password: Optional[str] = None, ssh_key: Optional[str] = None) -> bool:
        """
        Create a new admin (sudo) user on the VM.
        
        Args:
            username: Username for the new admin user
            password: Password for the new admin user (optional)
            ssh_key: SSH public key for the new admin user (optional)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not username:
            print("No username provided, skipping admin user creation")
            return False
            
        # Validate we have either a password or SSH key
        if not password and not ssh_key:
            print("ERROR: Must provide either a password or SSH key for the admin user")
            return False
            
        print(f"Creating admin user '{username}'...")
        
        # Create the user
        exit_code, _, stderr = self.ssh.execute_command(f"sudo adduser --gecos '' --disabled-password {username}")
        if exit_code != 0:
            print(f"Failed to create user {username}: {stderr}")
            return False
        
        # Add user to sudo group
        exit_code, _, stderr = self.ssh.execute_command(f"sudo usermod -aG sudo {username}")
        if exit_code != 0:
            print(f"Failed to add {username} to sudo group: {stderr}")
            return False
        
        # Set password if provided
        if password:
            print(f"Setting password for user {username}")
            # Generate a password hash and set it
            exit_code, _, stderr = self.ssh.execute_command(f"echo '{username}:{password}' | sudo chpasswd")
            if exit_code != 0:
                print(f"Failed to set password for {username}: {stderr}")
                return False
        else:
            print(f"No password provided for {username}, user will be SSH key access only")
        
        # Add SSH key (required if no password)
        if ssh_key:
            print(f"Setting up SSH key access for {username}")
            # Create .ssh directory
            self.ssh.execute_command(f"sudo mkdir -p /home/{username}/.ssh")
            
            # Add SSH key to authorized_keys
            exit_code, _, stderr = self.ssh.execute_command(f"echo '{ssh_key}' | sudo tee /home/{username}/.ssh/authorized_keys > /dev/null")
            if exit_code != 0:
                print(f"Failed to add SSH key for {username}: {stderr}")
                return False
            
            # Set proper permissions
            self.ssh.execute_command(f"sudo chmod 700 /home/{username}/.ssh")
            self.ssh.execute_command(f"sudo chmod 600 /home/{username}/.ssh/authorized_keys")
            self.ssh.execute_command(f"sudo chown -R {username}:{username} /home/{username}/.ssh")
        
        # Configure password-less sudo (always)
        print(f"Setting up passwordless sudo for {username}")
        exit_code, _, stderr = self.ssh.execute_command(f"echo '{username} ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/{username} > /dev/null")
        if exit_code != 0:
            print(f"Failed to configure sudo for {username}: {stderr}")
            return False
        
        # Set proper permissions for sudoers file
        self.ssh.execute_command(f"sudo chmod 440 /etc/sudoers.d/{username}")
        
        print(f"Admin user '{username}' created successfully")
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
    
    def _update_packages(self) -> bool:
        """
        Update system package lists.
        
        Returns:
            bool: True if successful, False otherwise
        """
        print("Updating package lists...")
        exit_code, _, stderr = self.ssh.execute_command("sudo apt-get update")
        if exit_code != 0:
            print(f"Failed to update package lists: {stderr}")
            return False
        return True
    
    def _install_essentials(self) -> bool:
        """
        Install essential packages.
        
        Returns:
            bool: True if successful, False otherwise
        """
        print("Installing common packages...")
        packages = [
            "curl",
            "wget",
            "git",
            "vim",
            "htop",
            "net-tools",
            "ca-certificates",
            "gnupg",
            "lsb-release",
            "apt-transport-https",
            "software-properties-common",
        ]
        
        exit_code, _, stderr = self.ssh.execute_command(f"sudo apt-get install -y {' '.join(packages)}")
        if exit_code != 0:
            print(f"Failed to install essential packages: {stderr}")
            return False
        return True
    
    def _install_qemu_agent(self) -> bool:
        """
        Install and configure the QEMU guest agent.
        
        Returns:
            bool: True if successful, False otherwise
        """
        print("Installing QEMU guest agent...")
        exit_code, _, stderr = self.ssh.execute_command("sudo apt-get install -y qemu-guest-agent")
        if exit_code != 0:
            print(f"Failed to install QEMU guest agent: {stderr}")
            return False
        
        # Enable and start the qemu-guest-agent service
        print("Enabling and starting QEMU guest agent...")
        exit_code, _, stderr = self.ssh.execute_command("sudo systemctl enable qemu-guest-agent")
        if exit_code != 0:
            print(f"Failed to enable QEMU guest agent: {stderr}")
            return False
            
        exit_code, _, stderr = self.ssh.execute_command("sudo systemctl start qemu-guest-agent")
        if exit_code != 0:
            print(f"Failed to start QEMU guest agent: {stderr}")
            return False
        
        # Mark the VM as having the agent installed if we have a reference to it
        if self.vm:
            print("Marking VM as having QEMU guest agent installed...")
            self.vm.set_agent_installed(True)
            
        return True 