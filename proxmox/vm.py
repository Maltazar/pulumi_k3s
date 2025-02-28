"""
Module for creating and managing Proxmox VMs using Pulumi.
"""

import pulumi
import pulumi_proxmoxve as proxmox
from typing import Dict, Any, Optional

class ProxmoxVM:
    """
    Create and manage a Proxmox VE virtual machine.
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
        ssh_public_key: str = None,
        network_bridge: str = "vmbr0",
        ip_address: Optional[str] = None,
        gateway: Optional[str] = None,
        dns_server: str = "8.8.8.8",
    ):
        """
        Initialize a new ProxmoxVM.
        
        Args:
            provider: The Proxmox provider
            name: Name of the VM
            node: Proxmox node name
            template_id: VM template ID
            cores: Number of CPU cores
            memory: Memory in MB
            description: VM description
            disk_size: Disk size (e.g., "20G")
            ssh_public_key: SSH public key for cloud-init
            network_bridge: Network bridge to use
            ip_address: Static IP address (optional, uses DHCP if not provided)
            gateway: Network gateway (required if ip_address is set)
            dns_server: DNS server
        """
        self.provider = provider
        self.name = name
        self.node = node
        self.template_id = template_id
        
        # Configure VM clone from template
        vm_args = {
            "node_name": node,
            "clone": proxmox.vm.VmCloneArgs(
                vm_id=int(template_id.split("/")[1]),
                full=True,
            ),
            "name": name,
            "description": description,
            "cpu": proxmox.vm.VmCpuArgs(
                cores=cores,
            ),
            "memory": proxmox.vm.VmMemoryArgs(
                dedicated=memory,
            ),
            "network_device": proxmox.vm.VmNetworkDeviceArgs(
                bridge=network_bridge,
                model="virtio",
            ),
            "on_boot": True,
        }
        
        # Add cloud-init configuration if SSH key is provided
        if ssh_public_key:
            cloud_init = {
                "user": "ubuntu",  # Default user for cloud-init
                "ssh_key": ssh_public_key,
            }
            
            # Add network configuration if static IP is provided
            if ip_address and gateway:
                cloud_init["ipconfig"] = [
                    f"ip={ip_address}/24,gw={gateway}"
                ]
                cloud_init["nameserver"] = dns_server
                
            vm_args["cloud_init"] = cloud_init
        
        # Create the VM
        self.vm = proxmox.vm.Vm(
            name,
            opts=pulumi.ResourceOptions(provider=provider),
            **vm_args
        )

    @property
    def ip_address(self) -> pulumi.Output[str]:
        """Get the VM IP address"""
        return self.vm.ip_addresses.apply(lambda addresses: addresses[0] if addresses else None)

    @property
    def vm_id(self) -> pulumi.Output[int]:
        """Get the VM ID"""
        return self.vm.vm_id

def create_proxmox_vm(
    provider: proxmox.Provider,
    config: Dict[str, Any],
    node: str,
    template_id: str,
    ip_config: Dict[str, str] = None,
) -> ProxmoxVM:
    """
    Create a Proxmox VM using the specified configuration.
    
    Args:
        provider: Proxmox provider
        config: VM configuration
        node: Node name
        template_id: Template ID
        ip_config: Optional IP configuration (ip_address, gateway, etc.)
        
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
        ssh_public_key=config.get("ssh_public_key", None),
        **ip_args
    ) 