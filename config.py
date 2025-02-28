"""
Configuration for the Pulumi program to set up Proxmox VMs and k3s.
"""

import pulumi
from pulumi import Config

# Create Config objects for each namespace
proxmox = Config("proxmox")
vm = Config("vm")
k3s = Config("k3s")
ansible = Config("ansible")

# Proxmox configuration
proxmox_config = {
    "endpoint": pulumi.config.get("proxmox:endpoint") or "https://proxmox.example.com:8006/api2/json",
    "username": pulumi.config.require("proxmox:username"),
    "password": pulumi.config.require_secret("proxmox:password"),
    "insecure": pulumi.config.get_bool("proxmox:insecure") or True,  # Skip TLS verification
    "node": pulumi.config.get("proxmox:node") or "pve",  # Default node name
}

# VM Base Configuration
vm_base_config = {
    "description": pulumi.config.get("vm:description") or "K3s node created with Pulumi",
    "template": pulumi.config.require("vm:template"),  # VM template ID
    "cores": pulumi.config.get_int("vm:cores") or 2,
    "memory": pulumi.config.get_int("vm:memory") or 4096,  # MB
    "disk_size": pulumi.config.get("vm:disk_size") or "20G",
    "ssh_public_key": pulumi.config.require("vm:ssh_public_key"),
    "ssh_private_key_path": pulumi.config.require("vm:ssh_private_key_path"),
    "ssh_user": pulumi.config.get("vm:ssh_user") or "ubuntu",
    "network_bridge": pulumi.config.get("vm:network_bridge") or "vmbr0",
}

# K3s Cluster Configuration
k3s_cluster_config = {
    # Master nodes
    "master_count": pulumi.config.get_int("k3s:master_count") or 1,
    "master_name_prefix": pulumi.config.get("k3s:master_name_prefix") or "k3s-master",
    "master_cores": pulumi.config.get_int("k3s:master_cores") or vm_base_config["cores"],
    "master_memory": pulumi.config.get_int("k3s:master_memory") or vm_base_config["memory"],
    
    # Worker nodes
    "worker_count": pulumi.config.get_int("k3s:worker_count") or 0,
    "worker_name_prefix": pulumi.config.get("k3s:worker_name_prefix") or "k3s-worker",
    "worker_cores": pulumi.config.get_int("k3s:worker_cores") or vm_base_config["cores"],
    "worker_memory": pulumi.config.get_int("k3s:worker_memory") or vm_base_config["memory"],
    
    # Static IP configuration (optional)
    "use_static_ips": pulumi.config.get_bool("k3s:use_static_ips") or False,
    "ip_network": pulumi.config.get("k3s:ip_network") or "192.168.1.0/24",
    "ip_gateway": pulumi.config.get("k3s:ip_gateway") or "192.168.1.1",
    "ip_start": pulumi.config.get_int("k3s:ip_start") or 100,  # e.g., 192.168.1.100, 192.168.1.101, etc.
    
    # k3s version and settings
    "version": pulumi.config.get("k3s:version") or "v1.29.2+k3s1",
    "install_args": pulumi.config.get("k3s:install_args") or "",
}

# Ansible Configuration
# Note: Additional configuration for all.yml can be set using the 'ansible:' prefix
# For example: pulumi config set ansible:system_timezone "America/New_York"
# These values will be passed as extra_vars to the Ansible playbook
ansible_config = {
    "repo_url": pulumi.config.get("ansible:repo_url") or "https://github.com/techno-tim/k3s-ansible.git",
    "repo_branch": pulumi.config.get("ansible:repo_branch") or "master",
    "local_path": pulumi.config.get("ansible:local_path") or "k3s-ansible",
    "use_ansible": pulumi.config.get_bool("ansible:use_ansible") or True,
    "cache_repo": pulumi.config.get_bool("ansible:cache_repo") or True,
    # Additional configuration values with 'ansible:' prefix will be passed 
    # directly to the all.yml file. See README for examples.
} 