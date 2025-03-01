"""
Module for creating and managing Proxmox VMs using Pulumi.
"""

import pulumi
import pulumi_proxmoxve as proxmox
from typing import Dict, Any, Optional, Callable, Literal
import re

def sanitize_ssh_key(key: Optional[str]) -> Optional[str]:
    """
    Sanitizes an SSH public key by removing extra whitespace, newlines, and carriage returns.
    Also verifies that the key looks like a valid SSH public key.
    
    Args:
        key: The SSH public key to sanitize
        
    Returns:
        The sanitized SSH public key, or None if the key is None
    """
    if not key:
        return None
        
    # Remove any leading/trailing whitespace, newlines, carriage returns
    sanitized = key.strip()
    
    # Simple regex to check if the key looks valid (starts with ssh-rsa, ssh-ed25519, etc.)
    if not re.match(r'^(ssh-rsa|ssh-ed25519|ssh-dss|ecdsa-[a-zA-Z0-9-]+)\s+[a-zA-Z0-9+/]+={0,2}(\s+.*)?$', sanitized):
        pulumi.log.warn("The SSH key does not appear to be in the expected format. Key format should be: 'ssh-rsa AAAAB3Nz... user@host'")
    
    # Log the sanitized key (first 20 chars)
    sanitized_preview = sanitized[:20] + "..." if len(sanitized) > 20 else sanitized
    pulumi.log.info(f"Using sanitized SSH key: {sanitized_preview}")
    
    return sanitized

# VM power state operations
VMPowerOp = Literal["start", "stop", "shutdown", "reset", "reboot"]

class ProxmoxVM:
    """
    Represents a Proxmox VM created from a template.
    """
    def __init__(
        self,
        provider: proxmox.Provider,
        name: str,
        node: str,
        template_id: str,
        cores: int = 2,
        memory: int = 4096,
        description: str = None,
        disk_size: str = "20G",
        disk_storage: str = "local-lvm",
        ssh_public_key: str = None,
        network_bridge: str = "vmbr0",
        vlan_tag: Optional[int] = None,  # Added vlan_tag parameter
        ip_address: Optional[str] = None,
        gateway: Optional[str] = None,
        dns_server: str = "8.8.8.8",
        vm_id: Optional[int] = None,
        start_on_create: bool = True,  # Added parameter to control VM startup
        opts: Optional[pulumi.ResourceOptions] = None,  # Resource options for the VM
    ):
        """
        Creates a new VM from a template in Proxmox.
        
        Args:
            provider: Pulumi Proxmox provider
            name: VM name
            node: Proxmox node name
            template_id: Template ID to clone from (format: pve/vmid or just vmid)
            cores: Number of CPU cores
            memory: Memory in MB
            description: VM description
            disk_size: Disk size (e.g., "20G")
            disk_storage: Storage location ID in Proxmox (e.g., "local-lvm", "ceph")
            ssh_public_key: SSH public key for cloud-init (file path or key content)
            network_bridge: Network bridge to use
            vlan_tag: VLAN tag for the network interface (optional)
            ip_address: Static IP address in CIDR notation (e.g., "192.168.1.100/24")
            gateway: Network gateway (required if ip_address is set)
            dns_server: DNS server
            vm_id: Specific VM ID to assign to the new VM
            start_on_create: Whether to start the VM after creation
            opts: Resource options for the VM
        """
        self.provider = provider
        self.name = name
        self.node = node
        self.template_id = template_id
        self._has_agent = False  # Flag to track if agent is installed
        
        # Sanitize the SSH key if provided
        if ssh_public_key:
            ssh_public_key = sanitize_ssh_key(ssh_public_key)
            pulumi.log.info(f"Setting up cloud-init for VM {name}")
        
        # Extract VM ID from template_id
        if "/" in template_id:
            template_vm_id = int(template_id.split("/")[1])
        else:
            template_vm_id = int(template_id)
        
        # Convert disk size to GB integer (e.g., "20G" -> 20)
        size_gb = 0
        if disk_size:
            try:
                # Handle formats like "20G" or "20GB" by removing all non-numeric characters
                size_gb = int(''.join(filter(str.isdigit, disk_size)))
            except ValueError:
                # Default to 20 if conversion fails
                size_gb = 20
                
        # Prepare VM arguments
        vm_args = {
            "node_name": node,
            "name": name,
            "clone": {
                "vm_id": template_vm_id,
                "full": True,
            },
            "cpu": {
                "cores": cores,
            },
            "memory": {
                "dedicated": memory,
            },
            "network_devices": [
                {
                    "bridge": network_bridge,
                    "model": "virtio",
                }
            ],
            "agent": {
                "enabled": True,
            },
            "on_boot": True,
            # Set the VM to start or not based on configuration
            "started": start_on_create,
        }
        
        # Add VLAN tag if provided
        if vlan_tag is not None:
            vm_args["network_devices"][0]["vlan_tag"] = vlan_tag
            
        # Add specific VM ID if provided
        if vm_id is not None:
            vm_args["vm_id"] = vm_id
            
        # Add disk configuration with a size that's guaranteed to be larger
        # than the template's disk size (which is around 13GB based on the error)
        if size_gb:
            # Make sure we have a size of at least 15GB to be safe
            size_gb = max(size_gb, 15)
            vm_args["disks"] = [
                {
                    "interface": "scsi0",
                    "datastore_id": disk_storage,
                    "size": size_gb,
                }
            ]
        
        # Add description if provided
        if description:
            vm_args["description"] = description
            
        # Add initialization configuration if SSH key is provided
        if ssh_public_key:
            init_config = {
                "type": "nocloud",
                "user_account": {
                    "username": "ubuntu",  # Default user for cloud-init
                    "keys": [ssh_public_key],
                }
            }
            
            # Add network configuration if static IP is provided
            if ip_address and gateway:
                init_config["ip_configs"] = [
                    {
                        "ipv4": {
                            "address": ip_address,
                            "gateway": gateway
                        }
                    }
                ]
                
                # Add DNS configuration
                init_config["dns"] = {
                    "servers": [dns_server]
                }
                
            vm_args["initialization"] = init_config

        # Create default resource options if none were provided
        if opts is None:
            opts = pulumi.ResourceOptions(
                provider=provider,
                custom_timeouts=pulumi.CustomTimeouts(
                    create="15m",  # Allow 15 minutes for creation (including startup)
                    update="15m",  # Allow 15 minutes for updates
                    delete="10m",  # Allow 10 minutes for deletion
                ),
                delete_before_replace=True,  # Delete old VM before creating a new one
            )
        else:
            # If options were provided, ensure the provider is set
            if opts.provider is None:
                opts = pulumi.ResourceOptions.merge(
                    opts,
                    pulumi.ResourceOptions(provider=provider)
                )
            
            # Also ensure timeouts are set
            if not hasattr(opts, 'custom_timeouts') or opts.custom_timeouts is None:
                opts = pulumi.ResourceOptions.merge(
                    opts,
                    pulumi.ResourceOptions(
                        custom_timeouts=pulumi.CustomTimeouts(
                            create="15m",
                            update="15m",
                            delete="10m",
                        )
                    )
                )
        
        # Log what we're doing
        if start_on_create:
            pulumi.log.info(f"Creating VM {name} (ID: {vm_id}) and starting it (may take several minutes)...")
        else:
            pulumi.log.info(f"Creating VM {name} (ID: {vm_id}) without starting it...")
        
        # Create the VM
        self.vm = proxmox.vm.VirtualMachine(
            name,
            **vm_args,
            opts=opts
        )

    def set_agent_installed(self, installed: bool = True) -> None:
        """
        Mark the VM as having the QEMU guest agent installed.
        This affects which power commands we use for the VM.
        
        Args:
            installed: Whether the agent is installed
        """
        self._has_agent = installed
        
    @property
    def has_agent(self) -> bool:
        """
        Returns whether the QEMU guest agent is installed on this VM.
        """
        return self._has_agent
    
    def power_operation(self, operation: VMPowerOp) -> pulumi.Output[str]:
        """
        Perform a power operation on the VM, using the appropriate command
        based on whether the QEMU guest agent is installed.
        
        Args:
            operation: The power operation to perform
            
        Returns:
            pulumi.Output[str]: The result of the operation
        """
        # Use hard power operations if the guest agent isn't installed
        if not self._has_agent:
            if operation == "shutdown":
                pulumi.log.info(f"Guest agent not installed on {self.name}. Using 'stop' instead of 'shutdown'.")
                operation = "stop"
            elif operation == "reboot":
                pulumi.log.info(f"Guest agent not installed on {self.name}. Using 'reset' instead of 'reboot'.")
                operation = "reset"
        
        # Use the VM resource's state getter
        state = self.vm.vm_state
        
        # Define what to do based on the operation
        if operation == "start":
            def start_vm(vm_state):
                if vm_state == "running":
                    pulumi.log.info(f"VM {self.name} is already running")
                    return None
                pulumi.log.info(f"Starting VM {self.name}...")
                return "start"
            return state.apply(start_vm)
            
        elif operation == "stop":
            def stop_vm(vm_state):
                if vm_state != "running":
                    pulumi.log.info(f"VM {self.name} is already stopped")
                    return None
                pulumi.log.info(f"Stopping VM {self.name} (hard stop)...")
                return "stop"
            return state.apply(stop_vm)
            
        elif operation == "reset":
            def reset_vm(vm_state):
                if vm_state != "running":
                    pulumi.log.info(f"VM {self.name} is not running, starting it...")
                    return "start"
                pulumi.log.info(f"Resetting VM {self.name} (hard reset)...")
                return "reset"
            return state.apply(reset_vm)
            
        elif operation == "shutdown":
            def shutdown_vm(vm_state):
                if vm_state != "running":
                    pulumi.log.info(f"VM {self.name} is already stopped")
                    return None
                pulumi.log.info(f"Shutting down VM {self.name} gracefully...")
                return "shutdown"
            return state.apply(shutdown_vm)
            
        elif operation == "reboot":
            def reboot_vm(vm_state):
                if vm_state != "running":
                    pulumi.log.info(f"VM {self.name} is not running, starting it...")
                    return "start"
                pulumi.log.info(f"Rebooting VM {self.name} gracefully...")
                return "reboot"
            return state.apply(reboot_vm)
            
        else:
            raise ValueError(f"Unsupported power operation: {operation}")

    @property
    def ip_address(self) -> pulumi.Output[str]:
        """
        Returns the IP address of the VM.
        """
        return self.vm.ipv4_addresses.apply(lambda addresses: addresses[0] if addresses else None)

    @property
    def vm_id(self) -> pulumi.Output[int]:
        """
        Returns the VM ID.
        """
        return self.vm.vm_id
        
    @property
    def state(self) -> pulumi.Output[str]:
        """
        Returns the current state of the VM (running, stopped, etc.)
        """
        return self.vm.vm_state
        
    def ensure_running(self) -> pulumi.Output[Any]:
        """
        Ensure that the VM is running.
        This helps avoid 'user name not set' errors when applying cloud-init changes.
        
        Returns:
            The result of the operation
        """
        return self.power_operation("start")
        
    def stop(self) -> pulumi.Output[Any]:
        """
        Stop the VM (hard stop if guest agent not available)
        
        Returns:
            The result of the operation
        """
        return self.power_operation("stop" if not self._has_agent else "shutdown")
        
    def restart(self) -> pulumi.Output[Any]:
        """
        Restart the VM (hard reset if guest agent not available)
        
        Returns:
            The result of the operation
        """
        return self.power_operation("reset" if not self._has_agent else "reboot")

def create_proxmox_vm(
    provider: proxmox.Provider,
    config: Dict[str, Any],
    node: str,
    template_id: str,
    ip_config: Dict[str, str] = None,
    vm_id: Optional[int] = None,
    start_on_create: bool = True,  # Added parameter to pass through
    opts: Optional[pulumi.ResourceOptions] = None,  # Added parameter for resource options
) -> ProxmoxVM:
    """
    Create a Proxmox VM using the specified configuration.
    
    Args:
        provider: Proxmox provider
        config: VM configuration
        node: Node name
        template_id: Template ID
        ip_config: Optional IP configuration (ip_address, gateway, etc.)
        vm_id: Specific VM ID to assign to the new VM
        start_on_create: Whether to start the VM after creation
        opts: Optional resource options to pass to the VM creation
        
    Returns:
        ProxmoxVM: The created VM instance
    """
    ip_args = {}
    if ip_config and "ip_address" in ip_config and "gateway" in ip_config:
        ip_args = {
            "ip_address": ip_config["ip_address"],
            "gateway": ip_config["gateway"],
            "dns_server": ip_config.get("dns_server", "8.8.8.8"),
        }
    
    # Create and return the VM with the provided options
    return ProxmoxVM(
        provider=provider,
        name=config["name"],
        node=node,
        template_id=template_id,
        cores=config["cores"],
        memory=config["memory"],
        description=config.get("description", ""),
        disk_size=config.get("disk_size", "20G"),
        disk_storage=config.get("disk_storage", "local-lvm"),
        ssh_public_key=config.get("ssh_public_key", None),
        vlan_tag=config.get("vlan_tag", None),
        vm_id=vm_id,
        start_on_create=start_on_create,  # Pass through the start parameter
        opts=opts,  # Pass through the resource options
        **ip_args
    ) 