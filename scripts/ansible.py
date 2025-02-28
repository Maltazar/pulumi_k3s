"""
Module for integrating with Ansible for k3s installation.
"""

import os
import subprocess
import tempfile
import shutil
import ipaddress
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

class AnsibleManager:
    """
    Class to manage Ansible integration for k3s installation.
    """
    
    def __init__(
        self,
        repo_url: str,
        repo_branch: str = "master",
        local_path: str = "k3s-ansible",
        cache_repo: bool = True,
    ):
        """
        Initialize a new AnsibleManager.
        
        Args:
            repo_url: GitHub repository URL
            repo_branch: Branch to clone
            local_path: Directory to clone into
            cache_repo: Whether to cache the repository
        """
        self.repo_url = repo_url
        self.repo_branch = repo_branch
        self.local_path = os.path.expanduser(f"~/{local_path}")
        self.cache_repo = cache_repo
        
        # Ensure ansible directory exists
        os.makedirs(os.path.dirname(self.local_path), exist_ok=True)
    
    def clone_repository(self) -> bool:
        """
        Clone the Ansible repository.
        
        Returns:
            bool: True if successful, False otherwise
        """
        # Check if the repository already exists
        if os.path.exists(self.local_path) and self.cache_repo:
            print(f"Repository already exists at {self.local_path}, updating...")
            try:
                # Pull latest changes
                subprocess.check_call(
                    ["git", "pull", "origin", self.repo_branch],
                    cwd=self.local_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                return True
            except subprocess.CalledProcessError as e:
                print(f"Failed to update repository: {str(e)}")
                # If pull fails, remove the directory and clone again
                shutil.rmtree(self.local_path, ignore_errors=True)
        else:
            # Remove directory if it exists but not caching
            if os.path.exists(self.local_path):
                shutil.rmtree(self.local_path, ignore_errors=True)
        
        # Clone the repository
        try:
            subprocess.check_call(
                ["git", "clone", "-b", self.repo_branch, self.repo_url, self.local_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to clone repository: {str(e)}")
            return False
    
    def generate_inventory(
        self,
        master_nodes: List[Dict[str, Any]],
        worker_nodes: List[Dict[str, Any]],
        k3s_version: str,
        ansible_user: str = "ubuntu",
        extra_vars: Dict[str, Any] = None,
    ) -> bool:
        """
        Generate Ansible inventory files based on node configurations.
        
        Args:
            master_nodes: List of master node configurations
            worker_nodes: List of worker node configurations
            k3s_version: K3s version to install
            ansible_user: SSH user for ansible
            extra_vars: Additional variables for group_vars/all.yml
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not os.path.exists(self.local_path):
            print(f"Ansible directory not found at {self.local_path}")
            return False
        
        # Prepare inventory directory structure
        inventory_dir = os.path.join(self.local_path, "inventory/my-cluster")
        os.makedirs(os.path.join(inventory_dir, "group_vars"), exist_ok=True)
        
        # Generate host_vars directory if it doesn't exist
        host_vars_dir = os.path.join(inventory_dir, "host_vars")
        os.makedirs(host_vars_dir, exist_ok=True)
        
        # Generate hosts.ini file based on Techno Tim's format
        with open(os.path.join(inventory_dir, "hosts.ini"), "w") as f:
            # Master nodes section
            f.write("[master]\n")
            for node in master_nodes:
                f.write(f"{node['ip']}\n")
            
            f.write("\n")
            
            # Worker nodes section
            f.write("[node]\n")
            for node in worker_nodes:
                f.write(f"{node['ip']}\n")
            
            f.write("\n")
            
            # Optional Proxmox section (commented out by default)
            f.write("# only required if proxmox_lxc_configure: true\n")
            f.write("# must contain all proxmox instances that have a master or worker node\n")
            f.write("# [proxmox]\n")
            f.write("# 192.168.30.43\n\n")
            
            # K3s cluster section
            f.write("[k3s_cluster:children]\n")
            f.write("master\n")
            f.write("node\n")
        
        # Generate group_vars/all.yml with all options from Techno Tim's sample
        # Set default values and override with extra_vars if provided
        api_endpoint = master_nodes[0]['ip'] if master_nodes else "127.0.0.1"
        system_timezone = extra_vars.get("system_timezone", "UTC")
        
        all_vars = {
            "k3s_version": k3s_version,
            "ansible_user": ansible_user,
            "systemd_dir": "/etc/systemd/system",
            "system_timezone": system_timezone,
            "apiserver_endpoint": api_endpoint,
            "flannel_iface": "eth0",  # Default for cloud-init VMs
            "k3s_token": extra_vars.get("k3s_token", "pulumi-generated-token"),
            
            # Add more options from Techno Tim's sample
            "metal_lb_mode": "layer2",
            "metal_lb_type": "native",
            "metal_lb_ip_range": extra_vars.get("metal_lb_ip_range", "192.168.1.150-192.168.1.160"),
            
            # Default server args
            "extra_server_args": "--disable servicelb --disable traefik --tls-san " + api_endpoint,
            "extra_agent_args": "",
            
            # Include any SSH key settings
            "ansible_ssh_private_key_file": extra_vars.get("ansible_ssh_private_key_file", "~/.ssh/id_rsa"),
        }
        
        # Add any extra variables
        if extra_vars:
            all_vars.update(extra_vars)
        
        # Write to all.yml using proper YAML format
        with open(os.path.join(inventory_dir, "group_vars", "all.yml"), "w") as f:
            f.write("---\n")
            for key, value in all_vars.items():
                if isinstance(value, str) and not value.startswith("-"):
                    f.write(f"{key}: \"{value}\"\n")
                else:
                    f.write(f"{key}: {value}\n")
        
        print(f"Ansible inventory generated at {inventory_dir}")
        return True
    
    def run_playbook(self, playbook_name: str = "site.yml") -> bool:
        """
        Run the Ansible playbook.
        
        Args:
            playbook_name: Name of the playbook to run
            
        Returns:
            bool: True if successful, False otherwise
        """
        playbook_path = os.path.join(self.local_path, playbook_name)
        inventory_path = os.path.join(self.local_path, "inventory/my-cluster")
        
        if not os.path.exists(playbook_path):
            print(f"Playbook not found at {playbook_path}")
            return False
        
        # Run ansible-playbook command
        try:
            print(f"Running Ansible playbook: {playbook_name}")
            subprocess.check_call(
                [
                    "ansible-playbook", 
                    "-i", inventory_path, 
                    playbook_path, 
                    "-b", 
                    "--become-user=root"
                ],
                cwd=self.local_path,
            )
            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to run Ansible playbook: {str(e)}")
            return False
    
    @staticmethod
    def calculate_ip_addresses(
        network: str,
        gateway: str,
        start_ip_offset: int,
        num_masters: int,
        num_workers: int,
    ) -> Tuple[List[str], List[str]]:
        """
        Calculate IP addresses for masters and workers.
        
        Args:
            network: CIDR network (e.g., 192.168.1.0/24)
            gateway: Gateway IP (e.g., 192.168.1.1)
            start_ip_offset: Starting IP offset (e.g., 100 for 192.168.1.100)
            num_masters: Number of master nodes
            num_workers: Number of worker nodes
            
        Returns:
            Tuple[List[str], List[str]]: (master_ips, worker_ips)
        """
        try:
            # Parse the network
            ip_network = ipaddress.IPv4Network(network)
            
            # Create IP list
            all_ips = []
            for i in range(num_masters + num_workers):
                offset = start_ip_offset + i
                ip = str(ip_network.network_address + offset)
                all_ips.append(ip)
            
            # Split into master and worker IPs
            master_ips = all_ips[:num_masters]
            worker_ips = all_ips[num_masters:]
            
            return master_ips, worker_ips
        except Exception as e:
            print(f"Error calculating IP addresses: {str(e)}")
            return [], [] 