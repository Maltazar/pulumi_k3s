"""
A Pulumi program to set up multiple Proxmox VMs and install k3s using Ansible.
"""

import os
import time
import pulumi
import pulumi_proxmoxve as proxmox
from typing import cast, Any, Dict, Optional, List
import random
import string

from config import proxmox_config, vm_base_config, k3s_cluster_config, ansible_config
from proxmox.vm import create_proxmox_vm
from scripts.ssh import SSHClient
from scripts.provision import VMProvisioner
from scripts.ansible import AnsibleManager

# Create the Proxmox provider
proxmox_provider = proxmox.Provider(
    "proxmoxve",
    endpoint=proxmox_config["endpoint"],
    username=proxmox_config["username"],
    password=proxmox_config["password"],
    insecure=proxmox_config["insecure"],
    opts=pulumi.ResourceOptions(delete_before_replace=True),
)

# Function to calculate static IP configurations
def calculate_static_ips() -> Dict[str, List[Dict[str, str]]]:
    """
    Calculate static IP configurations for master and worker nodes.
    
    Returns:
        Dict[str, List[Dict[str, str]]]: IP configurations
    """
    if not k3s_cluster_config["use_static_ips"]:
        return {"masters": [], "workers": []}
    
    # Calculate IPs for masters and workers
    master_ips, worker_ips = AnsibleManager.calculate_ip_addresses(
        network=k3s_cluster_config["ip_network"],
        gateway=k3s_cluster_config["ip_gateway"],
        start_ip_offset=k3s_cluster_config["ip_start"],
        num_masters=k3s_cluster_config["master_count"],
        num_workers=k3s_cluster_config["worker_count"],
    )
    
    # Create IP configs for masters
    master_configs = []
    for ip in master_ips:
        master_configs.append({
            "ip_address": ip,
            "gateway": k3s_cluster_config["ip_gateway"],
            "dns_server": "8.8.8.8",
        })
    
    # Create IP configs for workers
    worker_configs = []
    for ip in worker_ips:
        worker_configs.append({
            "ip_address": ip,
            "gateway": k3s_cluster_config["ip_gateway"],
            "dns_server": "8.8.8.8",
        })
    
    return {
        "masters": master_configs,
        "workers": worker_configs,
    }

# Calculate static IP configurations (if enabled)
ip_configs = calculate_static_ips()

# Create master nodes
master_vms = []
for i in range(k3s_cluster_config["master_count"]):
    master_name = f"{k3s_cluster_config['master_name_prefix']}-{i+1}"
    
    # Create VM configuration
    master_config = vm_base_config.copy()
    master_config.update({
        "name": master_name,
        "cores": k3s_cluster_config["master_cores"],
        "memory": k3s_cluster_config["master_memory"],
    })
    
    # Get IP configuration (if using static IPs)
    master_ip_config = ip_configs["masters"][i] if ip_configs["masters"] and i < len(ip_configs["masters"]) else None
    
    # Create the VM
    master_vm = create_proxmox_vm(
        provider=proxmox_provider,
        config=master_config,
        node=proxmox_config["node"],
        template_id=vm_base_config["template"],
        ip_config=master_ip_config,
    )
    
    master_vms.append(master_vm)

# Create worker nodes
worker_vms = []
for i in range(k3s_cluster_config["worker_count"]):
    worker_name = f"{k3s_cluster_config['worker_name_prefix']}-{i+1}"
    
    # Create VM configuration
    worker_config = vm_base_config.copy()
    worker_config.update({
        "name": worker_name,
        "cores": k3s_cluster_config["worker_cores"],
        "memory": k3s_cluster_config["worker_memory"],
    })
    
    # Get IP configuration (if using static IPs)
    worker_ip_config = ip_configs["workers"][i] if ip_configs["workers"] and i < len(ip_configs["workers"]) else None
    
    # Create the VM
    worker_vm = create_proxmox_vm(
        provider=proxmox_provider,
        config=worker_config,
        node=proxmox_config["node"],
        template_id=vm_base_config["template"],
        ip_config=worker_ip_config,
    )
    
    worker_vms.append(worker_vm)

# Get all VM IP addresses
master_ips = [vm.ip_address for vm in master_vms]
worker_ips = [vm.ip_address for vm in worker_vms]

# Function to provision VM with basic software
def provision_vm(name: str, ip_address: str) -> bool:
    """
    Provision a VM with default software.
    
    Args:
        name: VM name
        ip_address: IP address of the VM
        
    Returns:
        bool: True if successful, False otherwise
    """
    print(f"Provisioning VM {name} at {ip_address}...")
    
    # Connect to the VM via SSH
    ssh_client = SSHClient(
        host=ip_address,
        username=vm_base_config["ssh_user"],
        private_key_path=vm_base_config["ssh_private_key_path"],
    )
    
    # Retry connecting to allow time for VM to boot
    retry_count = 0
    max_retries = 10
    connected = False
    
    while retry_count < max_retries and not connected:
        print(f"Attempting to connect to {name} (try {retry_count + 1}/{max_retries})...")
        connected = ssh_client.connect()
        if not connected:
            time.sleep(10)
            retry_count += 1
    
    if not connected:
        print(f"Failed to connect to VM {name} via SSH. Skipping provisioning.")
        return False
    
    try:
        # Provision the VM with default software
        print(f"Provisioning VM {name} with default software...")
        provisioner = VMProvisioner(ssh_client)
        success = provisioner.provision()
        
        # Disconnect from the VM
        ssh_client.disconnect()
        
        return success
    except Exception as e:
        print(f"Error provisioning VM {name}: {str(e)}")
        return False
    finally:
        if ssh_client:
            ssh_client.disconnect()

# Function to set up k3s cluster using Ansible
def setup_k3s_cluster(
    master_node_ips: List[pulumi.Output[str]],
    worker_node_ips: List[pulumi.Output[str]],
) -> None:
    """
    Set up k3s cluster using Ansible.
    
    Args:
        master_node_ips: List of master node IP addresses
        worker_node_ips: List of worker node IP addresses
    """
    # Combine all IP addresses to know when we can proceed
    all_ips = master_node_ips + worker_node_ips
    
    # Function to execute when all IPs are available
    def on_ips_available(ips: List[str]) -> None:
        # Filter out None values and empty strings
        master_ips = [ip for ip in ips[:len(master_node_ips)] if ip]
        worker_ips = [ip for ip in ips[len(master_node_ips):] if ip]
        
        # If we don't have all IPs, we can't proceed
        if len(master_ips) != len(master_node_ips) or len(worker_ips) != len(worker_node_ips):
            print("Not all VM IPs are available yet. Waiting...")
            return
        
        print("All VM IPs are available. Provisioning VMs...")
        
        # First, provision all VMs with basic software
        for i, ip in enumerate(master_ips):
            name = f"{k3s_cluster_config['master_name_prefix']}-{i+1}"
            if not provision_vm(name, ip):
                print(f"Failed to provision master node {name}. Skipping k3s installation.")
                return
        
        for i, ip in enumerate(worker_ips):
            name = f"{k3s_cluster_config['worker_name_prefix']}-{i+1}"
            if not provision_vm(name, ip):
                print(f"Failed to provision worker node {name}. Skipping k3s installation.")
                return
        
        # If using Ansible for k3s installation
        if ansible_config["use_ansible"]:
            print("Setting up k3s cluster using Ansible...")
            
            # Create Ansible manager
            ansible = AnsibleManager(
                repo_url=ansible_config["repo_url"],
                repo_branch=ansible_config["repo_branch"],
                local_path=ansible_config["local_path"],
                cache_repo=ansible_config["cache_repo"],
            )
            
            # Clone repository
            if not ansible.clone_repository():
                print("Failed to clone Ansible repository. Skipping k3s installation.")
                return
            
            # Prepare node information
            master_nodes = []
            for i, ip in enumerate(master_ips):
                master_nodes.append({
                    "name": f"{k3s_cluster_config['master_name_prefix']}-{i+1}",
                    "ip": ip,
                })
            
            worker_nodes = []
            for i, ip in enumerate(worker_ips):
                worker_nodes.append({
                    "name": f"{k3s_cluster_config['worker_name_prefix']}-{i+1}",
                    "ip": ip,
                })
            
            # Generate a random token for k3s
            k3s_token = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            
            # Generate inventory
            # Start with basic required settings
            extra_vars = {
                "k3s_token": k3s_token,
                "ansible_ssh_private_key_file": os.path.expanduser(vm_base_config["ssh_private_key_path"]),
            }
            
            # Collect all Ansible-related configuration settings
            # Get all Pulumi config keys and filter for ones with 'ansible:' prefix
            config = pulumi.config.Config()
            for key in config.get_object('ansible') or {}:
                if key not in ['repo_url', 'repo_branch', 'local_path', 'use_ansible', 'cache_repo']:
                    # Convert key to the format expected by Ansible (remove ansible: prefix)
                    ansible_key = key
                    extra_vars[ansible_key] = config.get(f'ansible:{key}')
            
            print(f"Using Ansible configuration: {extra_vars}")
            
            if not ansible.generate_inventory(
                master_nodes=master_nodes,
                worker_nodes=worker_nodes,
                k3s_version=k3s_cluster_config["version"],
                ansible_user=vm_base_config["ssh_user"],
                extra_vars=extra_vars,
            ):
                print("Failed to generate Ansible inventory. Skipping k3s installation.")
                return
            
            # Run the playbook
            if ansible.run_playbook():
                print("k3s cluster setup completed successfully!")
                
                # Download kubeconfig
                kubeconfig_path = os.path.expanduser("~/k3s.yaml")
                print(f"You can download the kubeconfig from the first master node ({master_ips[0]}) using:")
                print(f"scp {vm_base_config['ssh_user']}@{master_ips[0]}:~/.kube/config {kubeconfig_path}")
            else:
                print("Failed to run Ansible playbook.")
    
    # Register the callback to execute once all IPs are available
    pulumi.All(*all_ips).apply(on_ips_available)

# Set up the k3s cluster using Ansible
setup_k3s_cluster(master_ips, worker_ips)

# Export the outputs
for i, vm in enumerate(master_vms):
    pulumi.export(f"master_{i+1}_id", vm.vm_id)
    pulumi.export(f"master_{i+1}_name", f"{k3s_cluster_config['master_name_prefix']}-{i+1}")
    pulumi.export(f"master_{i+1}_ip", vm.ip_address)

for i, vm in enumerate(worker_vms):
    pulumi.export(f"worker_{i+1}_id", vm.vm_id)
    pulumi.export(f"worker_{i+1}_name", f"{k3s_cluster_config['worker_name_prefix']}-{i+1}")
    pulumi.export(f"worker_{i+1}_ip", vm.ip_address)
