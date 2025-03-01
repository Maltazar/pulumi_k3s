"""
A Pulumi program to set up multiple Proxmox VMs and install k3s using Ansible.

Important notes about VM power operations:
- Before QEMU guest agent is installed, the VMs will use 'stop' and 'reset' operations
- After QEMU guest agent is installed, the VMs will use 'shutdown' and 'reboot' operations
- The VMProvisioner automatically marks VMs as having the agent installed after provisioning
"""

import os
import time
import pulumi
import pulumi_proxmoxve as proxmox
from typing import cast, Any, Dict, Optional, List
import random
import string

from config import proxmox_config, vm_base_config, k3s_cluster_config, ansible_config
from proxmox.vm import create_proxmox_vm, ProxmoxVM
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

# Helper function to read SSH key from file if it's a path
def read_ssh_key_if_path(key_path_or_content):
    """
    If the provided value looks like a file path and exists, read the file content.
    Otherwise, return the original value assuming it's already the key content.
    
    Args:
        key_path_or_content: Either a path to an SSH key file or the actual key content
        
    Returns:
        The SSH key content
    """
    if not key_path_or_content:
        return None
        
    # If it looks like a key (starts with ssh-rsa, ssh-ed25519, etc.), return as is
    if isinstance(key_path_or_content, str) and key_path_or_content.strip().startswith(('ssh-rsa', 'ssh-ed25519', 'ssh-dss', 'ecdsa-')):
        return key_path_or_content
        
    # If it looks like a file path, try to read it
    if isinstance(key_path_or_content, str) and (key_path_or_content.startswith('/') or key_path_or_content.startswith('~')):
        try:
            full_path = os.path.expanduser(key_path_or_content)
            if os.path.isfile(full_path):
                with open(full_path, 'r') as key_file:
                    key_content = key_file.read().strip()
                pulumi.log.info(f"Successfully read SSH key from file: {key_path_or_content}")
                return key_content
        except Exception as e:
            pulumi.log.error(f"Failed to read SSH key from file {key_path_or_content}: {str(e)}")
    
    # Return original if we couldn't process it
    return key_path_or_content

# Process the SSH keys in the configuration
if "ssh_public_key" in vm_base_config:
    vm_base_config["ssh_public_key"] = read_ssh_key_if_path(vm_base_config["ssh_public_key"])
    # Truncate key for logging to avoid exposing the entire key
    key_preview = vm_base_config["ssh_public_key"][:20] + "..." if vm_base_config["ssh_public_key"] else "None"
    pulumi.log.info(f"Using SSH public key: {key_preview}")
    
if "admin_ssh_key" in vm_base_config:
    vm_base_config["admin_ssh_key"] = read_ssh_key_if_path(vm_base_config["admin_ssh_key"])
    # Truncate key for logging to avoid exposing the entire key
    key_preview = vm_base_config["admin_ssh_key"][:20] + "..." if vm_base_config["admin_ssh_key"] else "None"
    pulumi.log.info(f"Using admin SSH key: {key_preview}")

# Function to ensure a VM is running
def ensure_vm_running(vm: ProxmoxVM, vm_name: str):
    """
    Ensure that a VM is running before applying updates
    This helps avoid 'user name not set' errors when applying cloud-init changes
    
    Uses appropriate power commands based on whether the guest agent is installed.
    
    Args:
        vm: ProxmoxVM instance
        vm_name: Name of the VM for logging
    """
    pulumi.log.info(f"Ensuring VM {vm_name} is running...")
    return vm.ensure_running()

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

# Generate VM IDs from the configured range if specified
vm_id_min = vm_base_config.get("vm_id_min")
vm_id_max = vm_base_config.get("vm_id_max")
vm_ids = []

if vm_id_min is not None and vm_id_max is not None:
    total_vms = k3s_cluster_config["master_count"] + k3s_cluster_config["worker_count"]
    # Check if the range is large enough for all VMs
    if vm_id_max - vm_id_min + 1 < total_vms:
        pulumi.log.warn(f"VM ID range {vm_id_min}-{vm_id_max} is not large enough for {total_vms} VMs. Some VMs will be assigned IDs automatically.")
        # Generate as many IDs as possible from the range
        vm_ids = list(range(vm_id_min, vm_id_max + 1))
    else:
        # Generate all IDs from the range
        vm_ids = list(range(vm_id_min, vm_id_min + total_vms))
    
    pulumi.log.info(f"Using VM IDs: {vm_ids}")

# Get VM start setting from configuration
start_on_create = vm_base_config.get("start_on_create", True)

# Log the VM startup configuration
if start_on_create:
    pulumi.log.info("VMs will be started automatically after creation")
    pulumi.log.info("This helps avoid 'user name not set' errors when applying cloud-init changes")
else:
    pulumi.log.warn("VMs will NOT be started automatically after creation")
    pulumi.log.warn("This may cause issues with cloud-init settings if VMs are not running")

# Helper function to create a VM with proper dependencies
def create_vm_with_deps(
    name: str,
    config: Dict[str, Any],
    ip_config: Optional[Dict[str, str]],
    vm_id: Optional[int],
    deps: List[pulumi.Resource] = None
) -> ProxmoxVM:
    """
    Create a VM with dependencies on previously created VMs.
    This ensures VMs are created and started sequentially to avoid contention.
    
    Args:
        name: VM name
        config: VM configuration
        ip_config: Optional IP configuration
        vm_id: Optional VM ID
        deps: List of resources this VM depends on
        
    Returns:
        ProxmoxVM: The created VM
    """
    # Create resource options with dependencies if specified
    opts = None
    if deps:
        # Create resource options with dependencies and custom timeouts
        opts = pulumi.ResourceOptions(
            depends_on=deps,
            custom_timeouts=pulumi.CustomTimeouts(
                create="20m",  # Allow 20 minutes for creation (including startup)
                update="15m",  # Allow 15 minutes for updates
                delete="10m",  # Allow 10 minutes for deletion
            ),
            delete_before_replace=True,  # Delete old VM before creating a new one
        )
    else:
        # Create resource options with just custom timeouts
        opts = pulumi.ResourceOptions(
            custom_timeouts=pulumi.CustomTimeouts(
                create="20m",
                update="15m",
                delete="10m",
            ),
            delete_before_replace=True,
        )
    
    pulumi.log.info(f"Creating VM {name} with ID {vm_id if vm_id else 'auto-assigned'} and dependencies on {len(deps) if deps else 0} other resources...")
    
    # Create the VM with proper provider and options
    return create_proxmox_vm(
        provider=proxmox_provider,
        config=config,
        node=proxmox_config["node"],
        template_id=vm_base_config["template"],
        ip_config=ip_config,
        vm_id=vm_id,
        start_on_create=start_on_create,
        opts=opts
    )

# Create master nodes sequentially to avoid lock contention
master_vms = []
last_vm = None
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
    
    # Get VM ID if available
    vm_id = vm_ids[i] if vm_ids and i < len(vm_ids) else None
    
    # Log what we're doing
    pulumi.log.info(f"Creating master node {master_name} (order: {i+1}/{k3s_cluster_config['master_count']})")
    
    try:
        # Create the VM with dependency on the last created VM
        deps = [last_vm.vm] if last_vm else None
        master_vm = create_vm_with_deps(
            name=master_name,
            config=master_config,
            ip_config=master_ip_config,
            vm_id=vm_id,
            deps=deps
        )
        
        master_vms.append(master_vm)
        last_vm = master_vm
    except Exception as e:
        # Log the error but continue to the next VM
        pulumi.log.error(f"Failed to create master node {master_name}: {str(e)}")
        # If we have no VMs yet, we need to prevent later VMs from being created
        if not master_vms:
            raise Exception(f"Failed to create the first master node {master_name}. Cannot continue without at least one master node.") from e

# Create worker nodes sequentially (after all masters are created)
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
    
    # Get VM ID if available (offset by number of master nodes)
    master_count = k3s_cluster_config["master_count"]
    vm_id = vm_ids[master_count + i] if vm_ids and (master_count + i) < len(vm_ids) else None
    
    # Log what we're doing
    pulumi.log.info(f"Creating worker node {worker_name} (order: {i+1}/{k3s_cluster_config['worker_count']})")
    
    try:
        # Create the VM with dependency on the last created VM
        deps = [last_vm.vm] if last_vm else None
        worker_vm = create_vm_with_deps(
            name=worker_name,
            config=worker_config,
            ip_config=worker_ip_config,
            vm_id=vm_id,
            deps=deps
        )
        
        worker_vms.append(worker_vm)
        last_vm = worker_vm
    except Exception as e:
        # Log the error but continue to the next VM
        pulumi.log.error(f"Failed to create worker node {worker_name}: {str(e)}")
        # Worker nodes are optional, so we can continue even if some fail

# Get all VM IP addresses
master_ips = [vm.ip_address for vm in master_vms]
worker_ips = [vm.ip_address for vm in worker_vms]

# Function to provision VM with basic software
def provision_vm(vm: ProxmoxVM, name: str, ip_address: str) -> bool:
    """
    Provision a VM with default software.
    
    Args:
        vm: The ProxmoxVM instance
        name: VM name
        ip_address: IP address of the VM
        
    Returns:
        bool: True if successful, False otherwise
    """
    print(f"Provisioning VM {name} at {ip_address}...")
    
    # Check if we should use admin user for subsequent connections
    # We'll try the default user first, then fall back to admin user if configured
    using_admin_user = vm_base_config.get("create_admin_user", False) and vm_base_config.get("admin_username")
    admin_username = vm_base_config.get("admin_username") if using_admin_user else None
    
    # Connect to the VM via SSH using the default user first
    ssh_client = SSHClient(
        host=ip_address,
        username=vm_base_config["ssh_user"],
        private_key_path=vm_base_config["ssh_private_key_path"],
        key_passphrase=vm_base_config["ssh_key_passphrase"],
    )
    
    # Retry connecting to allow time for VM to boot
    retry_count = 0
    max_retries = 15  # Increased from 10 to 15
    retry_delay_seconds = 15  # Increased from 10 to 15
    connected = False
    tried_admin_user = False
    
    while retry_count < max_retries and not connected:
        username = ssh_client.username
        print(f"Attempting to connect to {name} as '{username}' (try {retry_count + 1}/{max_retries})...")
        try:
            connected = ssh_client.connect()
            if connected:
                print(f"Successfully connected to {name} as '{username}'")
                break
            else:
                print(f"Failed to connect to {name} as '{username}', retrying in {retry_delay_seconds} seconds...")
        except Exception as e:
            print(f"Error connecting to {name} as '{username}': {str(e)}")
            
            # If we've tried a few times with the default user and we have an admin user,
            # try switching to the admin user
            if retry_count >= 3 and using_admin_user and not tried_admin_user:
                print(f"Trying to connect as admin user '{admin_username}'...")
                ssh_client.disconnect()
                ssh_client = SSHClient(
                    host=ip_address,
                    username=admin_username,
                    private_key_path=vm_base_config["ssh_private_key_path"],
                    key_passphrase=vm_base_config["ssh_key_passphrase"],
                )
                tried_admin_user = True
                # Don't increment retry count when switching users
                time.sleep(retry_delay_seconds)
                continue
            
            print(f"Retrying in {retry_delay_seconds} seconds...")
        
        # Wait before retrying
        time.sleep(retry_delay_seconds)
        retry_count += 1
    
    if not connected:
        print(f"Failed to connect to VM {name} via SSH after {max_retries} attempts. Skipping provisioning.")
        return False
    
    try:
        # Provision the VM with default software
        print(f"Provisioning VM {name} with default software...")
        provisioner = VMProvisioner(ssh_client)
        
        # Pass a reference to the VM to the provisioner
        provisioner.set_vm(vm)
        
        # Determine if we should create an admin user
        admin_username = None
        admin_password = None
        admin_ssh_key = None
        
        if vm_base_config.get("create_admin_user", False):
            admin_username = vm_base_config.get("admin_username")
            admin_password = vm_base_config.get("admin_password")
            admin_ssh_key = vm_base_config.get("admin_ssh_key")
        
        # Provision with retry logic
        retry_count = 0
        max_provisioning_retries = 3
        success = False
        
        while retry_count < max_provisioning_retries and not success:
            try:
                print(f"Provisioning attempt {retry_count + 1}/{max_provisioning_retries} for {name}...")
                success = provisioner.provision(
                    admin_username=admin_username,
                    admin_password=admin_password,
                    admin_ssh_key=admin_ssh_key
                )
                
                if success:
                    print(f"Successfully provisioned {name}")
                    break
                else:
                    print(f"Provisioning {name} returned false, retrying...")
            except Exception as e:
                print(f"Error during provisioning of {name}: {str(e)}, retrying...")
            
            # Wait before retrying
            time.sleep(retry_delay_seconds)
            retry_count += 1
        
        return success
    except Exception as e:
        print(f"Error provisioning VM {name}: {str(e)}")
        return False
    finally:
        if ssh_client:
            ssh_client.disconnect()

# Function to set up k3s cluster using Ansible
def setup_k3s_cluster(
    master_vms: List[ProxmoxVM],
    worker_vms: List[ProxmoxVM],
) -> None:
    """
    Set up k3s cluster using Ansible.
    
    Args:
        master_vms: List of master VM resources
        worker_vms: List of worker VM resources
    """
    # Get IP addresses from VMs
    master_node_ips = [vm.ip_address for vm in master_vms]
    worker_node_ips = [vm.ip_address for vm in worker_vms]
    
    # Combine all VM resources and IP addresses
    all_vms = master_vms + worker_vms
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
        
        print("All VM IPs are available. Ensuring VMs are running...")
        
        # Ensure all VMs are running before provisioning
        for i, vm in enumerate(all_vms):
            vm_name = vm.name
            # Get VM state and ensure it's running
            if not start_on_create:
                # If VMs aren't set to start on create, we need to ensure they're running
                # This operation will happen during Pulumi preview/up
                ensure_vm_running(vm, vm_name)
        
        print("Provisioning VMs with required software...")
        
        # Determine which user to use for SSH operations
        # If we're creating an admin user, we'll use that for all operations after provisioning
        using_admin_user = vm_base_config.get("create_admin_user", False) and vm_base_config.get("admin_username")
        if using_admin_user:
            admin_username = vm_base_config.get("admin_username")
            print(f"Admin user '{admin_username}' will be created and used for all operations after provisioning")
        
        # First, provision all VMs with basic software
        for i, ip in enumerate(master_ips):
            name = f"{k3s_cluster_config['master_name_prefix']}-{i+1}"
            if not provision_vm(master_vms[i], name, ip):
                print(f"Failed to provision master node {name}. Skipping k3s installation.")
                return
        
        for i, ip in enumerate(worker_ips):
            name = f"{k3s_cluster_config['worker_name_prefix']}-{i+1}"
            if not provision_vm(worker_vms[i], name, ip):
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
            
            # Get token from Pulumi config or generate a random token if not available
            config = pulumi.config.Config()
            k3s_token = config.get_secret("ansible:k3s_token")
            if not k3s_token:
                # Fallback to generating a token if not found in config
                k3s_token = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
                pulumi.log.warn("No k3s_token found in configuration. Using a randomly generated token. This token will not be saved for future use.")
            else:
                pulumi.log.info("Using k3s_token from Pulumi configuration")
            
            # Get API server endpoint from config
            apiserver_endpoint = config.get("ansible:apiserver_endpoint")
            if not apiserver_endpoint:
                pulumi.log.warn("No apiserver_endpoint found in configuration. This may cause issues with HA cluster setup.")
            
            # Generate inventory
            # Start with basic required settings
            extra_vars = {
                "k3s_token": k3s_token,
                "ansible_ssh_private_key_file": os.path.expanduser(vm_base_config["ssh_private_key_path"]),
            }
            
            # Add apiserver_endpoint if available
            if apiserver_endpoint:
                extra_vars["apiserver_endpoint"] = apiserver_endpoint
            
            # Determine which user to use for Ansible
            # If we created an admin user, use that for Ansible
            if using_admin_user:
                ansible_user = vm_base_config["admin_username"]
                print(f"Using admin user '{ansible_user}' for Ansible operations")
            else:
                ansible_user = vm_base_config["ssh_user"]
                print(f"Using default user '{ansible_user}' for Ansible operations")
            
            # Collect all Ansible-related configuration settings
            # Get all Pulumi config keys and filter for ones with 'ansible:' prefix
            config = pulumi.config.Config()
            for key in config.get_object('ansible') or {}:
                # Skip the keys we've already processed
                if key in ["repo_url", "repo_branch", "local_path", "use_ansible", "cache_repo"]:
                    continue
                
                # Add the key to extra_vars (without the 'ansible:' prefix)
                ansible_key = key
                extra_vars[ansible_key] = config.get(f'ansible:{key}')
            
            print(f"Using Ansible configuration: {extra_vars}")
            
            if not ansible.generate_inventory(
                master_nodes=master_nodes,
                worker_nodes=worker_nodes,
                k3s_version=k3s_cluster_config["version"],
                ansible_user=ansible_user,
                extra_vars=extra_vars,
            ):
                print("Failed to generate Ansible inventory. Skipping k3s installation.")
                return
            
            # Run Ansible playbook with retry logic
            retry_count = 0
            max_retries = 3
            retry_delay_seconds = 60
            success = False
            
            while retry_count < max_retries and not success:
                print(f"Running Ansible playbook (attempt {retry_count + 1}/{max_retries})...")
                try:
                    success = ansible.run_playbook()
                    if success:
                        print("Successfully set up k3s cluster with Ansible")
                        break
                    else:
                        print(f"Ansible playbook failed, retrying in {retry_delay_seconds} seconds...")
                except Exception as e:
                    print(f"Error running Ansible playbook: {str(e)}, retrying in {retry_delay_seconds} seconds...")
                
                # Wait before retrying
                time.sleep(retry_delay_seconds)
                retry_count += 1
            
            if not success:
                print(f"Failed to run Ansible playbook after {max_retries} attempts. k3s installation might be incomplete.")
    
    # When all IPs are available, run the provisioning and setup
    pulumi.Output.all(*all_ips).apply(on_ips_available)

# Pass the VM resources to the setup function
setup_k3s_cluster(master_vms, worker_vms)

# Export the outputs
for i, vm in enumerate(master_vms):
    pulumi.export(f"master_{i+1}_id", vm.vm_id)
    pulumi.export(f"master_{i+1}_name", f"{k3s_cluster_config['master_name_prefix']}-{i+1}")
    pulumi.export(f"master_{i+1}_ip", vm.ip_address)

for i, vm in enumerate(worker_vms):
    pulumi.export(f"worker_{i+1}_id", vm.vm_id)
    pulumi.export(f"worker_{i+1}_name", f"{k3s_cluster_config['worker_name_prefix']}-{i+1}")
    pulumi.export(f"worker_{i+1}_ip", vm.ip_address)
