"""
Module for creating and managing Proxmox VMs using Pulumi.
"""

import pulumi
import pulumi_proxmoxve as proxmox
from typing import Dict, Any, Optional

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
        ip_address: Optional[str] = None,
        gateway: Optional[str] = None,
        dns_server: str = "8.8.8.8",
        vm_id: Optional[int] = None,
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
            ssh_public_key: SSH public key for cloud-init
            network_bridge: Network bridge to use
            ip_address: Static IP address in CIDR notation (e.g., "192.168.1.100/24")
            gateway: Network gateway (required if ip_address is set)
            dns_server: DNS server
            vm_id: Specific VM ID to assign to the new VM
        """
        self.provider = provider
        self.name = name
        self.node = node
        self.template_id = template_id
        
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
        }
        
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
        
        # Create the VM
        self.vm = proxmox.vm.VirtualMachine(
            name,
            **vm_args,
            opts=pulumi.ResourceOptions(provider=provider)
        )

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

def create_proxmox_vm(
    provider: proxmox.Provider,
    config: Dict[str, Any],
    node: str,
    template_id: str,
    ip_config: Dict[str, str] = None,
    vm_id: Optional[int] = None,
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
        vm_id=vm_id,
        **ip_args
    ) 