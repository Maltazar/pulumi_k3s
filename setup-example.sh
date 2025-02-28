#!/bin/bash
set -e

# Colors for better output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Pulumi Proxmox K3s Deployment Example ===${NC}"
echo -e "${BLUE}This script will set up a complete Pulumi Proxmox K3s deployment${NC}"
echo -e "${BLUE}=============================================${NC}\n"

# Check if venv directory exists
if [ ! -d "venv" ]; then
    echo -e "${RED}Virtual environment not found.${NC}"
    echo -e "${YELLOW}Please run the bootstrap script first:${NC}"
    echo -e "${YELLOW}  chmod +x bootstrap.sh${NC}"
    echo -e "${YELLOW}  ./bootstrap.sh${NC}"
    exit 1
fi

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source venv/bin/activate

# Verify Pulumi is available
if ! command -v pulumi &> /dev/null; then
    echo -e "${RED}Pulumi command not found even after activating the virtual environment.${NC}"
    echo -e "${YELLOW}Please make sure Pulumi is installed correctly by running bootstrap.sh${NC}"
    exit 1
else
    echo -e "${GREEN}Pulumi is available - OK${NC}"
fi

# Check if pulumi stack already exists, create if it doesn't
if ! pulumi stack ls | grep -q "dev"; then
    echo -e "${YELLOW}Creating new Pulumi stack 'dev'...${NC}"
    pulumi stack init dev
else
    echo -e "${GREEN}Using existing Pulumi stack 'dev'${NC}"
fi

echo -e "${YELLOW}Configuring Pulumi project...${NC}"

# -----------------------------------------------------
# Configure Proxmox Connection
# -----------------------------------------------------
echo -e "${BLUE}Configuring Proxmox connection settings...${NC}"

# Ask for Proxmox details
echo -e "${YELLOW}Enter your Proxmox details:${NC}"
read -p "Proxmox endpoint URL [https://proxmox.example.com:8006/api2/json]: " proxmox_endpoint
proxmox_endpoint=${proxmox_endpoint:-"https://proxmox.example.com:8006/api2/json"}

read -p "Proxmox username (e.g., user@pam): " proxmox_username
while [ -z "$proxmox_username" ]; do
    echo -e "${RED}Username cannot be empty${NC}"
    read -p "Proxmox username (e.g., user@pam): " proxmox_username
done

read -sp "Proxmox password: " proxmox_password
echo
while [ -z "$proxmox_password" ]; do
    echo -e "${RED}Password cannot be empty${NC}"
    read -sp "Proxmox password: " proxmox_password
    echo
done

read -p "Proxmox node name [pve]: " proxmox_node
proxmox_node=${proxmox_node:-"pve"}

# Set Proxmox configuration
pulumi config set proxmox:endpoint "$proxmox_endpoint"
pulumi config set proxmox:username "$proxmox_username"
pulumi config set --secret proxmox:password "$proxmox_password"
pulumi config set proxmox:node "$proxmox_node"
pulumi config set proxmox:insecure "true"

# -----------------------------------------------------
# Configure VM Settings
# -----------------------------------------------------
echo -e "${BLUE}Configuring VM settings...${NC}"

# Ask for VM template details
echo -e "${YELLOW}Enter your VM template details:${NC}"
read -p "VM template ID (e.g., pve/vm/9000): " vm_template
while [ -z "$vm_template" ]; do
    echo -e "${RED}Template ID cannot be empty${NC}"
    read -p "VM template ID (e.g., pve/vm/9000): " vm_template
done

# SSH settings
echo -e "${YELLOW}Configure SSH access to the VMs:${NC}"
read -p "SSH username in VM template [ubuntu]: " ssh_user
ssh_user=${ssh_user:-"ubuntu"}

# Default to standard SSH key locations
default_ssh_key_path="$HOME/.ssh/id_rsa"
read -p "SSH private key path [$default_ssh_key_path]: " ssh_private_key_path
ssh_private_key_path=${ssh_private_key_path:-"$default_ssh_key_path"}

# If the SSH key doesn't exist, offer to create it
if [ ! -f "$ssh_private_key_path" ]; then
    echo -e "${RED}SSH private key not found at $ssh_private_key_path${NC}"
    echo -e "${YELLOW}Would you like to create a new SSH key pair? (y/n)${NC}"
    read -r create_key
    if [[ "$create_key" == "y" ]]; then
        ssh_private_key_path="$HOME/.ssh/id_rsa_k3s"
        ssh-keygen -t rsa -b 4096 -f "$ssh_private_key_path" -N ""
        echo -e "${GREEN}New SSH key pair created at $ssh_private_key_path${NC}"
    else
        echo -e "${YELLOW}Please specify a valid SSH key path${NC}"
        exit 1
    fi
fi

# Get the SSH public key path and read the content
ssh_public_key_path="${ssh_private_key_path}.pub"
if [ ! -f "$ssh_public_key_path" ]; then
    echo -e "${RED}SSH public key not found at $ssh_public_key_path${NC}"
    echo -e "${YELLOW}Please make sure your SSH key pair is properly set up${NC}"
    exit 1
fi
ssh_public_key=$(cat "$ssh_public_key_path")

# VM resources
read -p "Default VM cores [2]: " vm_cores
vm_cores=${vm_cores:-"2"}

read -p "Default VM memory in MB [4096]: " vm_memory
vm_memory=${vm_memory:-"4096"}

read -p "Default VM disk size [20G]: " vm_disk_size
vm_disk_size=${vm_disk_size:-"20G"}

read -p "VM network bridge [vmbr0]: " vm_network_bridge
vm_network_bridge=${vm_network_bridge:-"vmbr0"}

# Set VM configuration
pulumi config set vm:template "$vm_template"
pulumi config set vm:cores "$vm_cores"
pulumi config set vm:memory "$vm_memory"
pulumi config set vm:disk_size "$vm_disk_size"
pulumi config set vm:ssh_user "$ssh_user"
pulumi config set vm:ssh_public_key "$ssh_public_key"
pulumi config set vm:ssh_private_key_path "$ssh_private_key_path"
pulumi config set vm:network_bridge "$vm_network_bridge"

# -----------------------------------------------------
# Configure K3s Cluster Settings
# -----------------------------------------------------
echo -e "${BLUE}Configuring K3s cluster settings...${NC}"

# Ask for cluster details
read -p "Number of master nodes [3]: " master_count
master_count=${master_count:-"3"}

read -p "Number of worker nodes [2]: " worker_count
worker_count=${worker_count:-"2"}

read -p "Master node name prefix [k3s-master]: " master_prefix
master_prefix=${master_prefix:-"k3s-master"}

read -p "Worker node name prefix [k3s-worker]: " worker_prefix
worker_prefix=${worker_prefix:-"k3s-worker"}

read -p "Master node cores [2]: " master_cores
master_cores=${master_cores:-"2"}

read -p "Master node memory in MB [4096]: " master_memory
master_memory=${master_memory:-"4096"}

read -p "Worker node cores [4]: " worker_cores
worker_cores=${worker_cores:-"4"}

read -p "Worker node memory in MB [8192]: " worker_memory
worker_memory=${worker_memory:-"8192"}

read -p "K3s version [v1.29.2+k3s1]: " k3s_version
k3s_version=${k3s_version:-"v1.29.2+k3s1"}

# Static IP configuration
echo -e "${YELLOW}Do you want to use static IPs for the VMs? (y/n) [n]:${NC}"
read -r use_static_ips
use_static_ips=${use_static_ips:-"n"}

if [[ "$use_static_ips" == "y" ]]; then
    pulumi config set k3s:use_static_ips "true"
    
    read -p "IP network CIDR [192.168.1.0/24]: " ip_network
    ip_network=${ip_network:-"192.168.1.0/24"}
    
    read -p "IP gateway [192.168.1.1]: " ip_gateway
    ip_gateway=${ip_gateway:-"192.168.1.1"}
    
    read -p "Starting IP offset (e.g., 100 for 192.168.1.100) [100]: " ip_start
    ip_start=${ip_start:-"100"}
    
    pulumi config set k3s:ip_network "$ip_network"
    pulumi config set k3s:ip_gateway "$ip_gateway"
    pulumi config set k3s:ip_start "$ip_start"
else
    pulumi config set k3s:use_static_ips "false"
fi

# Set K3s configuration
pulumi config set k3s:master_count "$master_count"
pulumi config set k3s:master_name_prefix "$master_prefix"
pulumi config set k3s:master_cores "$master_cores"
pulumi config set k3s:master_memory "$master_memory"
pulumi config set k3s:worker_count "$worker_count"
pulumi config set k3s:worker_name_prefix "$worker_prefix"
pulumi config set k3s:worker_cores "$worker_cores"
pulumi config set k3s:worker_memory "$worker_memory"
pulumi config set k3s:version "$k3s_version"
pulumi config set k3s:install_args "--disable=traefik"

# -----------------------------------------------------
# Configure Ansible Settings
# -----------------------------------------------------
echo -e "${BLUE}Configuring Ansible settings...${NC}"

read -p "Ansible repository URL [https://github.com/techno-tim/k3s-ansible.git]: " ansible_repo_url
ansible_repo_url=${ansible_repo_url:-"https://github.com/techno-tim/k3s-ansible.git"}

read -p "Ansible repository branch [master]: " ansible_repo_branch
ansible_repo_branch=${ansible_repo_branch:-"master"}

read -p "Ansible local path [k3s-ansible]: " ansible_local_path
ansible_local_path=${ansible_local_path:-"k3s-ansible"}

echo -e "${YELLOW}Cache the Ansible repository locally? (y/n) [y]:${NC}"
read -r ansible_cache_repo
ansible_cache_repo=${ansible_cache_repo:-"y"}
if [[ "$ansible_cache_repo" == "y" ]]; then
    ansible_cache_repo_bool="true"
else
    ansible_cache_repo_bool="false"
fi

# Set Ansible configuration
pulumi config set ansible:repo_url "$ansible_repo_url"
pulumi config set ansible:repo_branch "$ansible_repo_branch"
pulumi config set ansible:local_path "$ansible_local_path"
pulumi config set ansible:use_ansible "true"
pulumi config set ansible:cache_repo "$ansible_cache_repo_bool"

# -----------------------------------------------------
# Configure Ansible Extra Variables (all.yml)
# -----------------------------------------------------
echo -e "${BLUE}Configuring Ansible extra variables (all.yml)...${NC}"

read -p "System timezone [America/New_York]: " system_timezone
system_timezone=${system_timezone:-"America/New_York"}
pulumi config set ansible:system_timezone "$system_timezone"

# Load balancer IP range
read -p "MetalLB IP range for LoadBalancer services [192.168.1.150-192.168.1.160]: " metal_lb_ip_range
metal_lb_ip_range=${metal_lb_ip_range:-"192.168.1.150-192.168.1.160"}
pulumi config set ansible:metal_lb_ip_range "$metal_lb_ip_range"

# Network interface
read -p "Network interface for K3s [eth0]: " flannel_iface
flannel_iface=${flannel_iface:-"eth0"}
pulumi config set ansible:flannel_iface "$flannel_iface"

# Pod CIDR
read -p "Pod CIDR range [10.42.0.0/16]: " cluster_cidr
cluster_cidr=${cluster_cidr:-"10.42.0.0/16"}
pulumi config set ansible:cluster_cidr "$cluster_cidr"

# Network CNI options
echo -e "${YELLOW}Which CNI would you like to use?${NC}"
echo -e "  1) Flannel (default)"
echo -e "  2) Calico"
echo -e "  3) Cilium"
read -p "Choose a CNI [1]: " cni_choice
cni_choice=${cni_choice:-"1"}

if [[ "$cni_choice" == "2" ]]; then
    echo -e "${YELLOW}Configuring Calico CNI...${NC}"
    pulumi config set ansible:calico_iface "$flannel_iface"
    pulumi config set ansible:calico_tag "v3.28.0"
elif [[ "$cni_choice" == "3" ]]; then
    echo -e "${YELLOW}Configuring Cilium CNI...${NC}"
    pulumi config set ansible:cilium_iface "$flannel_iface"
    pulumi config set ansible:cilium_mode "native"
    pulumi config set ansible:cilium_tag "v1.16.0"
    pulumi config set ansible:cilium_hubble "true"
else
    echo -e "${YELLOW}Using default Flannel CNI${NC}"
fi

# -----------------------------------------------------
# Deploy the Pulumi Stack
# -----------------------------------------------------
echo -e "\n${BLUE}=== Configuration Complete ===${NC}"
echo -e "${YELLOW}Would you like to deploy the stack now? (y/n) [y]:${NC}"
read -r deploy_now
deploy_now=${deploy_now:-"y"}

if [[ "$deploy_now" == "y" ]]; then
    echo -e "${BLUE}Deploying Pulumi stack...${NC}"
    pulumi up

    echo -e "\n${GREEN}===========================================${NC}"
    echo -e "${GREEN}Deployment has been initiated!${NC}"
    echo -e "${GREEN}===========================================${NC}"
    echo -e "\n${BLUE}Once the deployment completes successfully, get the kubeconfig with:${NC}"
    echo -e "${YELLOW}  scp $ssh_user@<master-1-ip>:~/.kube/config ~/k3s.yaml${NC}"
    echo -e "${YELLOW}  export KUBECONFIG=~/k3s.yaml${NC}"
    echo -e "${YELLOW}  kubectl get nodes${NC}"
else
    echo -e "\n${GREEN}===========================================${NC}"
    echo -e "${GREEN}Configuration complete! Ready to deploy.${NC}"
    echo -e "${GREEN}===========================================${NC}"
    echo -e "\n${BLUE}To deploy the stack, run:${NC}"
    echo -e "${YELLOW}  pulumi up${NC}"
    echo -e "\n${BLUE}After deployment, get the kubeconfig with:${NC}"
    echo -e "${YELLOW}  scp $ssh_user@<master-1-ip>:~/.kube/config ~/k3s.yaml${NC}"
    echo -e "${YELLOW}  export KUBECONFIG=~/k3s.yaml${NC}"
    echo -e "${YELLOW}  kubectl get nodes${NC}"
fi

echo -e "\n${BLUE}To clean up all resources when you're done:${NC}"
echo -e "${YELLOW}  pulumi destroy${NC}" 