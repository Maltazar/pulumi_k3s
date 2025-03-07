# Pulumi Proxmox K3s Cluster Setup

!!! DOES NOT WORK YET!

This Pulumi project automates setting up a Kubernetes cluster on Proxmox VMs using K3s and Ansible. It provides a complete infrastructure-as-code solution for:

1. Creating multiple Proxmox VMs (masters and workers)
2. Provisioning them with essential software
3. Installing and configuring K3s using Techno Tim's [k3s-ansible](https://github.com/techno-tim/k3s-ansible) playbook

## Prerequisites

- [Pulumi CLI](https://www.pulumi.com/docs/install/) installed
- Python 3.12+
- Access to a Proxmox server
- SSH keys generated (`ssh-keygen -t rsa -b 4096`)
- A VM template in Proxmox with cloud-init support
- Ansible installed on your local machine (`apt install ansible` or equivalent for your OS)

## Quick Start with Helper Scripts

This project includes two helper scripts to simplify the setup and deployment process:

### 1. Bootstrap Script

The `bootstrap.sh` script sets up your local environment automatically:

```bash
# Make the script executable
chmod +x bootstrap.sh

# Run the bootstrap script
./bootstrap.sh
```

This script will:
- Check for required dependencies (Python, venv, Pulumi CLI, Ansible)
- Offer to install missing dependencies
- Create a Python virtual environment
- Install required Python packages
- Set up the basic project structure

### 2. Example Setup Script

After bootstrapping, use the `setup-config.sh` script for guided configuration and deployment:

```bash
# Make the script executable
chmod +x setup-config.sh

# Run the setup script
./setup-config.sh

# Skip prompts for existing configuration values
SKIP_EXISTING_CONFIG=1 ./setup-config.sh

# Enable debug logging
DEBUG=1 ./setup-config.sh

# Combine flags
SKIP_EXISTING_CONFIG=1 DEBUG=1 ./setup-config.sh
```

This interactive script will:
- Automatically activate the virtual environment
- Guide you through configuring Proxmox connection details
- Help set up VM template and resource specifications
- Configure K3s cluster parameters (number of nodes, resources, etc.)
- Set up Ansible integration with Techno Tim's playbook
- Allow you to customize CNI and other cluster features
- Optionally deploy the stack when configuration is complete
- Detect and use existing configuration values from your Pulumi stack, 
  making it easy to update existing configurations

The script supports the following environment variables:
- `SKIP_EXISTING_CONFIG=1`: Only prompt for configuration values that don't exist yet
- `DEBUG=1`: Enable detailed debug logging

The setup script fully leverages Pulumi's configuration system, reading existing values from the Pulumi.dev.yaml file when available. This approach allows you to:

1. Keep all configurations in the Pulumi stack
2. View your full configuration with `pulumi config`
3. Easily modify settings with `pulumi config set` commands
4. Run the setup script multiple times to modify only specific settings
5. Have a consistent source of truth for all configuration values

The setup script handles special configuration requirements, such as parameters that start with `--`, ensuring
that everything is properly set up for Pulumi.

**Note**: If you prefer to configure things manually instead of using the guided setup script, you can use the Pulumi commands in the Configuration section below.

## Cluster Architecture

By default, this project creates:
- 3 master nodes (for high availability)
- 2 worker nodes (for workload distribution)

You can easily customize the number of nodes through configuration settings.

## Configuration

Before deploying, set the necessary configuration values using the Pulumi CLI:

### Proxmox Configuration

```bash
# Set Proxmox connection details
pulumi config set proxmox:endpoint https://your-proxmox-server:8006/api2/json
pulumi config set proxmox:username your-username@pam
pulumi config set --secret proxmox:password your-password
pulumi config set proxmox:node pve  # Your Proxmox node name
```

### VM Base Configuration

```bash
# Set VM template and SSH information
pulumi config set vm:template your-template-id  # e.g., "pve/vm/9000"
pulumi config set vm:cores 2                    # Default cores per VM
pulumi config set vm:memory 4096                # Default memory per VM (MB)
pulumi config set vm:disk_size 20G              # Default disk size
pulumi config set vm:disk_storage local-lvm     # Storage location in Proxmox
pulumi config set vm:ssh_user ubuntu            # Username in the template

# SSH keys can be specified either as file paths or as the actual key content
pulumi config set vm:ssh_public_key "$(cat ~/.ssh/id_rsa.pub)"  # Using content from file
# OR directly specify the file path:
pulumi config set vm:ssh_public_key ~/.ssh/id_rsa.pub  # Will be read automatically

pulumi config set vm:ssh_private_key_path ~/.ssh/id_rsa
pulumi config set --secret vm:ssh_key_passphrase "your-key-passphrase"  # Optional: If your key has a passphrase
pulumi config set vm:network_bridge vmbr0       # Network bridge to use
pulumi config set vm:vlan_tag 10                # Optional: VLAN tag for network interfaces

# Optional: VM ID range configuration
pulumi config set vm:vm_id_min 1000             # Minimum VM ID to use
pulumi config set vm:vm_id_max 1050             # Maximum VM ID to use

# Optional: Admin user configuration
pulumi config set vm:create_admin_user true     # Create admin user on the VMs
pulumi config set vm:admin_username k3s-admin   # Username for the admin user
pulumi config set --secret vm:admin_password "secure-password"  # Optional admin password

# Admin SSH key can be specified either as a file path or as the actual key content
pulumi config set vm:admin_ssh_key "$(cat ~/.ssh/id_rsa.pub)"  # Using content from file
# OR directly specify the file path:
pulumi config set vm:admin_ssh_key ~/.ssh/id_rsa.pub  # Will be read automatically
```

The provisioning process will:
1. Create and configure VMs with the specified settings
2. Install essential packages including qemu-guest-agent
3. Set up an optional admin user with sudo privileges (if configured)
4. Install and configure K3s across all nodes

### Admin User Feature

When enabled, the admin user feature:

- Creates a new user with sudo privileges on each VM
- Sets up passwordless sudo for the admin user (always enabled)
- Requires either a password or SSH key (or both) for authentication
- Uses this admin user for all operations after provisioning, including Ansible
- Improves security by avoiding the default cloud-init user for ongoing operations

If you don't provide a password for the admin user, the user will be SSH key only (passwordless login). This is often more secure than password-based authentication. You must provide an SSH key in this case.

### K3s Cluster Configuration

```bash
# Master nodes configuration
pulumi config set k3s:master_count 3            # Number of master nodes
pulumi config set k3s:master_name_prefix k3s-master
pulumi config set k3s:master_cores 2            # Cores for masters
pulumi config set k3s:master_memory 4096        # Memory for masters (MB)

# Worker nodes configuration
pulumi config set k3s:worker_count 2            # Number of worker nodes
pulumi config set k3s:worker_name_prefix k3s-worker
pulumi config set k3s:worker_cores 4            # Cores for workers
pulumi config set k3s:worker_memory 8192        # Memory for workers (MB)

# Optional: Static IP configuration
pulumi config set k3s:use_static_ips false      # Set to true to use static IPs
pulumi config set k3s:ip_network 192.168.1.0/24 # Your network
pulumi config set k3s:ip_gateway 192.168.1.1    # Your gateway
pulumi config set k3s:ip_start 100              # Starting IP offset (e.g., 192.168.1.100)

# K3s version
pulumi config set k3s:version v1.29.2+k3s1
pulumi config set k3s:install_args "--disable=traefik"  # Optional install arguments
```

### Ansible Configuration

```bash
# Ansible configuration for k3s installation
pulumi config set ansible:repo_url https://github.com/techno-tim/k3s-ansible.git
pulumi config set ansible:repo_branch master
pulumi config set ansible:local_path k3s-ansible  # Local directory for the repo
pulumi config set ansible:use_ansible true        # Set to false to skip Ansible
pulumi config set ansible:cache_repo true         # Cache the repository locally
```

### Customizing Ansible Configuration (all.yml)

You can customize the Ansible configuration by setting additional variables that will be included in the `all.yml` file. The project passes these variables to Ansible through the `extra_vars` parameter.

Add these variables using the `ansible:` prefix in your Pulumi config:

```bash
# Basic settings
pulumi config set ansible:system_timezone "America/New_York"  # System timezone for all nodes
pulumi config set ansible:metal_lb_ip_range "192.168.1.150-192.168.1.160"  # IP range for LoadBalancer services

# Networking settings
pulumi config set ansible:flannel_iface "eth0"  # Network interface for K3s
pulumi config set ansible:cluster_cidr "10.42.0.0/16"  # Pod CIDR range

# K3s Cluster Settings (Required for HA setup)
pulumi config set ansible:apiserver_endpoint "192.168.1.200"  # Virtual IP for K3s API server
pulumi config set --secret ansible:k3s_token "your-secure-token"  # Cluster token (will be auto-generated if not provided)

# K3s server settings
pulumi config set ansible:extra_server_args "--disable servicelb --disable traefik --node-taint node-role.kubernetes.io/master=true:NoSchedule"

# K3s agent settings
pulumi config set ansible:extra_agent_args "--node-label worker=true"

# Advanced Settings: Switching CNI
# Use Calico instead of Flannel (default)
pulumi config set ansible:calico_iface "eth0"  # Enable Calico CNI
pulumi config set ansible:calico_tag "v3.28.0"  # Calico version

# Or use Cilium instead
# pulumi config set ansible:cilium_iface "eth0"  # Enable Cilium CNI
# pulumi config set ansible:cilium_mode "native"  # Cilium mode
# pulumi config set ansible:cilium_tag "v1.16.0"  # Cilium version
# pulumi config set ansible:cilium_hubble "true"  # Enable Hubble observability

# MetalLB configuration
pulumi config set ansible:metal_lb_mode "layer2"  # layer2 or bgp
pulumi config set ansible:metal_lb_type "native"  # native or frr
pulumi config set ansible:metal_lb_speaker_tag_version "v0.14.8"  # MetalLB version
pulumi config set ansible:metal_lb_controller_tag_version "v0.14.8"

# BGP configuration for MetalLB or Cilium (if using BGP mode)
# pulumi config set ansible:metal_lb_bgp_my_asn "64513"
# pulumi config set ansible:metal_lb_bgp_peer_asn "64512"
# pulumi config set ansible:metal_lb_bgp_peer_address "192.168.30.1"
```

These settings correspond directly to variables in Techno Tim's `all.yml` configuration. You can reference the [original configuration file](https://github.com/techno-tim/k3s-ansible/blob/master/inventory/sample/group_vars/all.yml) for additional options.

When you run the Pulumi deployment, all these settings will be automatically included in the generated `all.yml` file.

## Deployment

### Using Helper Scripts (Recommended)

The simplest way to deploy this project is using the provided helper scripts:

1. Run the bootstrap script to set up your environment:
   ```bash
   chmod +x bootstrap.sh
   ./bootstrap.sh
   ```

2. Run the interactive setup script which will guide you through configuration and deployment:
   ```bash
   chmod +x setup-config.sh
   ./setup-config.sh
   ```

### Manual Deployment

If you prefer to configure and deploy manually:

1. Install the required Python dependencies:

```bash
pip install -r requirements.txt
```

2. Configure all settings as described in the Configuration section above

3. Deploy the stack:

```bash
pulumi up
```

### Accessing Your Cluster

When the deployment completes successfully, you'll see the IPs of all master and worker nodes.

The kubeconfig file will be available on the first master node. You can download it using:

```bash
scp ubuntu@<master-1-ip>:~/.kube/config ~/k3s.yaml
export KUBECONFIG=~/k3s.yaml
kubectl get nodes
```

## How It Works

1. **VM Creation**: Pulumi creates the specified number of master and worker VMs on your Proxmox server
2. **VM Provisioning**: Each VM is provisioned with essential software
3. **Ansible Integration**: The project clones the k3s-ansible repo and generates the inventory based on your configuration
4. **K3s Installation**: Ansible runs the playbook to install K3s across all nodes

### Ansible Inventory Generation

This project automatically generates Ansible inventory files according to Techno Tim's k3s-ansible playbook requirements:

- **hosts.ini**: Lists master and worker nodes with their IP addresses
- **group_vars/all.yml**: Contains K3s configuration variables including versions, network settings, and optional features

The inventory is created in the `inventory/my-cluster` directory within the cloned repository path.

## Clean Up

To destroy all resources created by this Pulumi stack:

```bash
pulumi destroy
```

## Project Structure

- `__main__.py`: Main Pulumi program
- `config.py`: Configuration variables
- `proxmox/`: Modules for interacting with Proxmox
- `scripts/`: Utility scripts for VM provisioning, SSH, and Ansible integration

## Customization

You can customize the deployment by modifying the configuration values or editing the source code to add additional functionality.

## Troubleshooting

- If Ansible fails to connect to the VMs, ensure that SSH keys are properly set up and that the VMs can be reached via SSH
- Check that the VM template has cloud-init properly configured
- Verify that the Proxmox firewall allows connections between VMs
- For detailed logs, run pulumi with verbose output: `pulumi up --verbose=3`
- If Ansible inventory files are incorrectly generated, check the `~/k3s-ansible/inventory/my-cluster` directory
- To manually run the Ansible playbook after deployment: `cd ~/k3s-ansible && ansible-playbook -i inventory/my-cluster site.yml -b --become-user=root`
- Check Ansible logs for any errors by examining the output during the Pulumi deployment 

### Network Configuration

- **VLAN Tags**: If you're using VLAN tags, ensure that your Proxmox host and network switches are properly configured to pass VLAN traffic. The VMs will be created with the specified VLAN tag on their network interfaces.

- **API Server Endpoint**: For HA setups, the `apiserver_endpoint` must be a virtual IP (VIP) that can float between master nodes. This IP should be:
  - In the same subnet as your master nodes
  - Not assigned to any physical device
  - Reachable from all nodes in the cluster
  - If using MetalLB, make sure the VIP is outside the MetalLB range

- **K3s Token**: The k3s_token is used for node authentication to join the cluster. For security:
  - The token is automatically generated if not provided
  - A manually set token can be more easily remembered for future manual operations
  - The token is stored securely in Pulumi's configuration

### VM Power Operations

When managing VMs through this Pulumi program, it's important to understand how power operations work:

- **Before Guest Agent Installation**: 
  - The program uses `stop` and `reset` operations for VMs that don't have the QEMU guest agent installed yet
  - These are "hard" power operations similar to unplugging a computer

- **After Guest Agent Installation**:
  - Once the QEMU guest agent is installed during provisioning, the program automatically switches to `shutdown` and `reboot` operations
  - These are "graceful" power operations that allow the OS to shut down properly

If you're seeing timeout errors during deployment when Pulumi tries to shut down or reboot VMs, it could be because the guest agent isn't installed yet. The program now handles this automatically, but be aware that the first deployment might behave differently from subsequent ones.

## Managing Pulumi State

If you encounter issues with Pulumi state or need to perform advanced state operations, these commands will help:

### Refreshing Pulumi State

If you've made changes to your infrastructure outside of Pulumi (like manually deleting VMs in Proxmox), refresh Pulumi's state:

```bash
pulumi refresh
```

This command will update Pulumi's state file to match the actual infrastructure without making any changes to the resources.

### Handling Manually Deleted Resources

If you manually deleted VMs or other resources and now Pulumi is failing with errors like "the requested resource does not exist":

1. First, refresh Pulumi's state to acknowledge the missing resources:
   ```bash
   pulumi refresh
   ```

2. Then run your update to recreate the resources:
   ```bash
   pulumi up
   ```

### Advanced State Management

For more fine-grained control over Pulumi state:

- **Remove a specific resource from state** (when it no longer exists and can't be refreshed):
  ```bash
  pulumi state delete <resource-URN>
  ```
  You can find the URN in error messages or by running `pulumi stack export`

- **View detailed state information**:
  ```bash
  pulumi stack export > pulumi-state.json
  ```

- **Import existing resources into Pulumi**:
  ```bash
  pulumi import <resource-type> <resource-name> <resource-id>
  ```
  
### Force Resource Replacement

If you need to recreate a specific resource without destroying everything:

```bash
pulumi up --target <resource-URN> --replace
```

This is useful when you need to recreate a single VM without rebuilding your entire cluster. 