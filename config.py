"""
Configuration for the Pulumi program to set up Proxmox VMs and k3s.
"""

import pulumi
from pulumi import Config

# Create Config objects for each namespace
proxmox_config_obj = Config("proxmox")
vm_config_obj = Config("vm")
k3s_config_obj = Config("k3s")
ansible_config_obj = Config("ansible")

# Proxmox configuration
proxmox_config = {
    "endpoint": proxmox_config_obj.get("endpoint") or "https://proxmox.example.com:8006/api2/json",
    "username": proxmox_config_obj.require("username"),
    "password": proxmox_config_obj.require_secret("password"),
    "insecure": proxmox_config_obj.get_bool("insecure") or True,  # Skip TLS verification
    "node": proxmox_config_obj.get("node") or "pve",  # Default node name
}

# VM Base Configuration
vm_base_config = {
    "description": vm_config_obj.get("description") or "K3s node created with Pulumi",
    "template": vm_config_obj.require("template"),  # VM template ID
    "cores": vm_config_obj.get_int("cores") or 2,
    "memory": vm_config_obj.get_int("memory") or 4096,  # MB
    "disk_size": vm_config_obj.get("disk_size") or "20G",
    "ssh_public_key": vm_config_obj.require("ssh_public_key"),
    "ssh_private_key_path": vm_config_obj.require("ssh_private_key_path"),
    "ssh_user": vm_config_obj.get("ssh_user") or "ubuntu",
    "network_bridge": vm_config_obj.get("network_bridge") or "vmbr0",
}

# K3s Cluster Configuration
k3s_cluster_config = {
    # Master nodes
    "master_count": k3s_config_obj.get_int("master_count") or 1,
    "master_name_prefix": k3s_config_obj.get("master_name_prefix") or "k3s-master",
    "master_cores": k3s_config_obj.get_int("master_cores") or vm_base_config["cores"],
    "master_memory": k3s_config_obj.get_int("master_memory") or vm_base_config["memory"],
    
    # Worker nodes
    "worker_count": k3s_config_obj.get_int("worker_count") or 0,
    "worker_name_prefix": k3s_config_obj.get("worker_name_prefix") or "k3s-worker",
    "worker_cores": k3s_config_obj.get_int("worker_cores") or vm_base_config["cores"],
    "worker_memory": k3s_config_obj.get_int("worker_memory") or vm_base_config["memory"],
    
    # Static IP configuration (optional)
    "use_static_ips": k3s_config_obj.get_bool("use_static_ips") or False,
    "ip_network": k3s_config_obj.get("ip_network") or "192.168.1.0/24",
    "ip_gateway": k3s_config_obj.get("ip_gateway") or "192.168.1.1",
    "ip_start": k3s_config_obj.get_int("ip_start") or 100,  # e.g., 192.168.1.100, 192.168.1.101, etc.
    
    # k3s version and settings
    "version": k3s_config_obj.get("version") or "v1.29.2+k3s1",
    "install_args": k3s_config_obj.get("install_args") or "",
}

# Ansible Configuration
# Note: Additional configuration for all.yml can be set using the 'ansible:' prefix
# For example: pulumi config set ansible:system_timezone "America/New_York"
# These values will be passed as extra_vars to the Ansible playbook
ansible_config = {
    "repo_url": ansible_config_obj.get("repo_url") or "https://github.com/techno-tim/k3s-ansible.git",
    "repo_branch": ansible_config_obj.get("repo_branch") or "master",
    "local_path": ansible_config_obj.get("local_path") or "k3s-ansible",
    "use_ansible": ansible_config_obj.get_bool("use_ansible") or True,
    "cache_repo": ansible_config_obj.get_bool("cache_repo") or True,
    # Additional configuration values with 'ansible:' prefix will be passed 
    # directly to the all.yml file. See README for examples.
} 