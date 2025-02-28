#!/bin/bash
set -e

# Colors for better output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

# Enable debug mode with DEBUG=1 ./setup-example.sh
DEBUG=${DEBUG:-0}

debug_log() {
    if [ "$DEBUG" -eq 1 ]; then
        echo -e "${GRAY}[DEBUG] $1${NC}" >&2
    fi
}

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

# Function to safely set Pulumi config
# Handles values that start with - or -- correctly
safe_config_set() {
    local key=$1
    local value=$2
    local secret=$3
    
    debug_log "Setting config $key = $value (secret: $secret)"
    
    if [[ "$value" == -* ]]; then
        # Handle values starting with - or -- by using the -- separator
        if [[ "$secret" == "true" ]]; then
            pulumi config set --secret "$key" -- "$value"
        else
            pulumi config set "$key" -- "$value"
        fi
    else
        # Regular values without dashes at the start
        if [[ "$secret" == "true" ]]; then
            pulumi config set --secret "$key" "$value"
        else
            pulumi config set "$key" "$value"
        fi
    fi
}

# Function to get existing pulumi config or default
get_config_or_default() {
    local key=$1
    local default=$2
    
    debug_log "Getting config for $key (default is from Pulumi.dev.yaml or code default)"
    # Get the value directly with pulumi config get
    local value=$(pulumi config get "$key" 2>/dev/null)
    local result=$?
    
    if [ $result -eq 0 ]; then
        debug_log "Found existing config for $key: $value"
        echo "$value"
    else
        debug_log "No existing config for $key, using default"
        echo "$default"
    fi
}

# Check for existing Pulumi stack and configuration
has_existing_stack=false
has_config=false

# Check if the stack exists
if pulumi stack ls 2>/dev/null | grep -q "dev"; then
    has_existing_stack=true
    
    # Check if the stack has configuration by trying to get any config value
    if pulumi config 2>/dev/null | grep -q ":"; then
        has_config=true
        echo -e "${GREEN}Found existing Pulumi stack 'dev' with configuration${NC}"
        echo -e "${YELLOW}Will use existing values as defaults${NC}"
        
        if [ "$DEBUG" -eq 1 ]; then
            echo -e "${GRAY}[DEBUG] Current stack configuration:${NC}"
            pulumi config
        fi
    else
        echo -e "${GREEN}Found existing Pulumi stack 'dev' but no configuration${NC}"
    fi
else
    echo -e "${YELLOW}Creating new Pulumi stack 'dev'...${NC}"
    pulumi stack init dev
fi

echo -e "${YELLOW}Configuring Pulumi project...${NC}"

# -----------------------------------------------------
# Configure Proxmox Connection
# -----------------------------------------------------
echo -e "${BLUE}Configuring Proxmox connection settings...${NC}"

# Prompt for Proxmox details
echo -e "${YELLOW}Enter your Proxmox details:${NC}"
stored_endpoint=$(get_config_or_default "proxmox:endpoint" "")
echo -n "Proxmox endpoint URL [$stored_endpoint]: "
read input_endpoint
proxmox_endpoint=${input_endpoint:-"$stored_endpoint"}

stored_username=$(get_config_or_default "proxmox:username" "")
echo -n "Proxmox username (e.g., user@pam) [$stored_username]: "
read input_username
proxmox_username=${input_username:-"$stored_username"}

# Check that username is not empty
while [ -z "$proxmox_username" ]; do
    echo -e "${RED}Username cannot be empty${NC}"
    echo -n "Proxmox username (e.g., user@pam): "
    read proxmox_username
done

# Get Proxmox password - special handling for secrets
if pulumi config get proxmox:password &>/dev/null; then
    echo -e "${GREEN}Using existing secret for proxmox:password${NC}"
    proxmox_password=""
else
    echo -n "Proxmox password: "
    read -s proxmox_password
    echo
    
    # Check that password is not empty
    while [ -z "$proxmox_password" ]; do
        echo -e "${RED}Password cannot be empty${NC}"
        echo -n "Proxmox password: "
        read -s proxmox_password
        echo
    done
fi

stored_node=$(get_config_or_default "proxmox:node" "")
echo -n "Proxmox node name [$stored_node]: "
read input_node
proxmox_node=${input_node:-"$stored_node"}

# Set Proxmox configuration
safe_config_set "proxmox:endpoint" "$proxmox_endpoint"
safe_config_set "proxmox:username" "$proxmox_username"
if [ -n "$proxmox_password" ]; then
    safe_config_set "proxmox:password" "$proxmox_password" "true"
fi
safe_config_set "proxmox:node" "$proxmox_node"
safe_config_set "proxmox:insecure" "true"

# -----------------------------------------------------
# Configure VM Settings
# -----------------------------------------------------
echo -e "${BLUE}Configuring VM settings...${NC}"

# VM Template
echo -e "${YELLOW}Enter your VM template details:${NC}"
stored_template=$(get_config_or_default "vm:template" "")
echo -n "VM template ID [$stored_template]: "
read input_template
vm_template=${input_template:-"$stored_template"}

# Check that template is not empty
while [ -z "$vm_template" ]; do
    echo -e "${RED}Template ID cannot be empty${NC}"
    echo -n "VM template ID: "
    read vm_template
done

# VM SSH Settings
echo -e "${YELLOW}Configure SSH access to the VMs:${NC}"
stored_ssh_user=$(get_config_or_default "vm:ssh_user" "")
echo -n "SSH username [$stored_ssh_user]: "
read input_ssh_user
ssh_user=${input_ssh_user:-"$stored_ssh_user"}

stored_ssh_private_key_path=$(get_config_or_default "vm:ssh_private_key_path" "$HOME/.ssh/id_rsa")
echo -n "SSH private key path [$stored_ssh_private_key_path]: "
read input_ssh_private_key_path
ssh_private_key_path=${input_ssh_private_key_path:-"$stored_ssh_private_key_path"}

# Check if the private key exists
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

# Get public key content
if [ -f "${ssh_private_key_path}.pub" ]; then
    default_ssh_public_key=$(cat "${ssh_private_key_path}.pub")
elif [ -f "$ssh_private_key_path" ]; then
    # Try to generate public key from private key
    default_ssh_public_key=$(ssh-keygen -y -f "$ssh_private_key_path" 2>/dev/null)
    if [ $? -ne 0 ]; then
        default_ssh_public_key=""
    fi
else
    default_ssh_public_key=""
fi

stored_ssh_public_key=$(get_config_or_default "vm:ssh_public_key" "$default_ssh_public_key")
if [ ${#stored_ssh_public_key} -gt 40 ]; then
    # If key is long, only show beginning
    display_key="${stored_ssh_public_key:0:40}..."
else
    display_key="$stored_ssh_public_key"
fi
echo -n "SSH public key [$display_key]: "
read input_ssh_public_key
ssh_public_key=${input_ssh_public_key:-"$stored_ssh_public_key"}

# VM Resources
echo -e "${YELLOW}Configure VM resources:${NC}"
stored_cores=$(get_config_or_default "vm:cores" "")
echo -n "Default VM cores [$stored_cores]: "
read input_cores
vm_cores=${input_cores:-"$stored_cores"}

stored_memory=$(get_config_or_default "vm:memory" "")
echo -n "Default VM memory in MB [$stored_memory]: "
read input_memory
vm_memory=${input_memory:-"$stored_memory"}

stored_disk_size=$(get_config_or_default "vm:disk_size" "")
echo -n "Default VM disk size [$stored_disk_size]: "
read input_disk_size
vm_disk_size=${input_disk_size:-"$stored_disk_size"}

stored_network_bridge=$(get_config_or_default "vm:network_bridge" "")
echo -n "VM network bridge [$stored_network_bridge]: "
read input_network_bridge
vm_network_bridge=${input_network_bridge:-"$stored_network_bridge"}

# Set VM configuration
safe_config_set "vm:template" "$vm_template"
safe_config_set "vm:cores" "$vm_cores"
safe_config_set "vm:memory" "$vm_memory"
safe_config_set "vm:disk_size" "$vm_disk_size"
safe_config_set "vm:ssh_user" "$ssh_user"
safe_config_set "vm:ssh_public_key" "$ssh_public_key"
safe_config_set "vm:ssh_private_key_path" "$ssh_private_key_path"
safe_config_set "vm:network_bridge" "$vm_network_bridge"

# -----------------------------------------------------
# Configure K3s Cluster Settings
# -----------------------------------------------------
echo -e "${BLUE}Configuring K3s cluster settings...${NC}"

# Master nodes
stored_master_count=$(get_config_or_default "k3s:master_count" "")
echo -n "Number of master nodes [$stored_master_count]: "
read input_master_count
master_count=${input_master_count:-"$stored_master_count"}

# Worker nodes
stored_worker_count=$(get_config_or_default "k3s:worker_count" "")
echo -n "Number of worker nodes [$stored_worker_count]: "
read input_worker_count
worker_count=${input_worker_count:-"$stored_worker_count"}

# Name prefixes
stored_master_prefix=$(get_config_or_default "k3s:master_name_prefix" "")
echo -n "Master node name prefix [$stored_master_prefix]: "
read input_master_prefix
master_prefix=${input_master_prefix:-"$stored_master_prefix"}

stored_worker_prefix=$(get_config_or_default "k3s:worker_name_prefix" "")
echo -n "Worker node name prefix [$stored_worker_prefix]: "
read input_worker_prefix
worker_prefix=${input_worker_prefix:-"$stored_worker_prefix"}

# Resource allocation
stored_master_cores=$(get_config_or_default "k3s:master_cores" "")
echo -n "Master node cores [$stored_master_cores]: "
read input_master_cores
master_cores=${input_master_cores:-"$stored_master_cores"}

stored_master_memory=$(get_config_or_default "k3s:master_memory" "")
echo -n "Master node memory in MB [$stored_master_memory]: "
read input_master_memory
master_memory=${input_master_memory:-"$stored_master_memory"}

stored_worker_cores=$(get_config_or_default "k3s:worker_cores" "")
echo -n "Worker node cores [$stored_worker_cores]: "
read input_worker_cores
worker_cores=${input_worker_cores:-"$stored_worker_cores"}

stored_worker_memory=$(get_config_or_default "k3s:worker_memory" "")
echo -n "Worker node memory in MB [$stored_worker_memory]: "
read input_worker_memory
worker_memory=${input_worker_memory:-"$stored_worker_memory"}

# K3s version
stored_k3s_version=$(get_config_or_default "k3s:version" "")
echo -n "K3s version [$stored_k3s_version]: "
read input_k3s_version
k3s_version=${input_k3s_version:-"$stored_k3s_version"}

# Static IP configuration
stored_use_static_ips=$(get_config_or_default "k3s:use_static_ips" "")

# Convert true/false to y/n for user interaction if needed
if [[ "$stored_use_static_ips" == "true" ]]; then
    stored_use_static_ips="y"
elif [[ "$stored_use_static_ips" == "false" ]]; then
    stored_use_static_ips="n"
fi

echo -n "Do you want to use static IPs for the VMs? (y/n) [$stored_use_static_ips]: "
read input_use_static_ips
use_static_ips=${input_use_static_ips:-"$stored_use_static_ips"}

if [[ "$use_static_ips" == "y" ]]; then
    safe_config_set "k3s:use_static_ips" "true"
    
    stored_ip_network=$(get_config_or_default "k3s:ip_network" "")
    echo -n "IP network CIDR [$stored_ip_network]: "
    read input_ip_network
    ip_network=${input_ip_network:-"$stored_ip_network"}
    
    stored_ip_gateway=$(get_config_or_default "k3s:ip_gateway" "")
    echo -n "IP gateway [$stored_ip_gateway]: "
    read input_ip_gateway
    ip_gateway=${input_ip_gateway:-"$stored_ip_gateway"}
    
    stored_ip_start=$(get_config_or_default "k3s:ip_start" "")
    echo -n "Starting IP offset (e.g., 100 for 192.168.1.100) [$stored_ip_start]: "
    read input_ip_start
    ip_start=${input_ip_start:-"$stored_ip_start"}
    
    safe_config_set "k3s:ip_network" "$ip_network"
    safe_config_set "k3s:ip_gateway" "$ip_gateway"
    safe_config_set "k3s:ip_start" "$ip_start"
else
    safe_config_set "k3s:use_static_ips" "false"
fi

# Set K3s configuration
safe_config_set "k3s:master_count" "$master_count"
safe_config_set "k3s:master_name_prefix" "$master_prefix"
safe_config_set "k3s:master_cores" "$master_cores"
safe_config_set "k3s:master_memory" "$master_memory"
safe_config_set "k3s:worker_count" "$worker_count"
safe_config_set "k3s:worker_name_prefix" "$worker_prefix"
safe_config_set "k3s:worker_cores" "$worker_cores"
safe_config_set "k3s:worker_memory" "$worker_memory"
safe_config_set "k3s:version" "$k3s_version"

# Note: Using the special -- syntax for values that start with -
stored_install_args=$(get_config_or_default "k3s:install_args" "")
echo -n "K3s install args [$stored_install_args]: "
read input_install_args
install_args=${input_install_args:-"$stored_install_args"}

safe_config_set "k3s:install_args" "$install_args"

# -----------------------------------------------------
# Configure Ansible Settings
# -----------------------------------------------------
echo -e "${BLUE}Configuring Ansible settings...${NC}"

stored_repo_url=$(get_config_or_default "ansible:repo_url" "")
echo -n "Ansible repository URL [$stored_repo_url]: "
read input_repo_url
ansible_repo_url=${input_repo_url:-"$stored_repo_url"}

stored_repo_branch=$(get_config_or_default "ansible:repo_branch" "")
echo -n "Ansible repository branch [$stored_repo_branch]: "
read input_repo_branch
ansible_repo_branch=${input_repo_branch:-"$stored_repo_branch"}

stored_local_path=$(get_config_or_default "ansible:local_path" "")
echo -n "Ansible local path [$stored_local_path]: "
read input_local_path
ansible_local_path=${input_local_path:-"$stored_local_path"}

stored_cache_repo=$(get_config_or_default "ansible:cache_repo" "")

# Convert true/false to y/n for user interaction if needed
if [[ "$stored_cache_repo" == "true" ]]; then
    stored_cache_repo="y"
elif [[ "$stored_cache_repo" == "false" ]]; then
    stored_cache_repo="n"
fi

echo -n "Cache the Ansible repository locally? (y/n) [$stored_cache_repo]: "
read input_cache_repo
ansible_cache_repo=${input_cache_repo:-"$stored_cache_repo"}

if [[ "$ansible_cache_repo" == "y" ]]; then
    ansible_cache_repo_bool="true"
else
    ansible_cache_repo_bool="false"
fi

# Set Ansible configuration
safe_config_set "ansible:repo_url" "$ansible_repo_url"
safe_config_set "ansible:repo_branch" "$ansible_repo_branch"
safe_config_set "ansible:local_path" "$ansible_local_path"
safe_config_set "ansible:use_ansible" "true"
safe_config_set "ansible:cache_repo" "$ansible_cache_repo_bool"

# -----------------------------------------------------
# Configure Ansible Extra Variables (all.yml)
# -----------------------------------------------------
echo -e "${BLUE}Configuring Ansible extra variables (all.yml)...${NC}"

stored_timezone=$(get_config_or_default "ansible:system_timezone" "")
echo -n "System timezone [$stored_timezone]: "
read input_timezone
system_timezone=${input_timezone:-"$stored_timezone"}

safe_config_set "ansible:system_timezone" "$system_timezone"

# Load balancer IP range
stored_lb_range=$(get_config_or_default "ansible:metal_lb_ip_range" "")
echo -n "MetalLB IP range for LoadBalancer services [$stored_lb_range]: "
read input_lb_range
metal_lb_ip_range=${input_lb_range:-"$stored_lb_range"}

safe_config_set "ansible:metal_lb_ip_range" "$metal_lb_ip_range"

# Network interface
stored_iface=$(get_config_or_default "ansible:flannel_iface" "")
echo -n "Network interface for K3s [$stored_iface]: "
read input_iface
flannel_iface=${input_iface:-"$stored_iface"}

safe_config_set "ansible:flannel_iface" "$flannel_iface"

# Pod CIDR
stored_cidr=$(get_config_or_default "ansible:cluster_cidr" "")
echo -n "Pod CIDR range [$stored_cidr]: "
read input_cidr
cluster_cidr=${input_cidr:-"$stored_cidr"}

safe_config_set "ansible:cluster_cidr" "$cluster_cidr"

# Network CNI options
echo -e "${YELLOW}Which CNI would you like to use?${NC}"
echo -e "  1) Flannel (default)"
echo -e "  2) Calico"
echo -e "  3) Cilium"

# Check if we already have a CNI configured
has_calico=$(grep -q "^  ansible:calico_iface:" Pulumi.dev.yaml 2>/dev/null && echo "true" || echo "false")
has_cilium=$(grep -q "^  ansible:cilium_iface:" Pulumi.dev.yaml 2>/dev/null && echo "true" || echo "false")

cni_default="1"
if [[ "$has_calico" == "true" ]]; then
    cni_default="2"
    echo -e "${YELLOW}Detected existing Calico configuration${NC}"
elif [[ "$has_cilium" == "true" ]]; then
    cni_default="3"
    echo -e "${YELLOW}Detected existing Cilium configuration${NC}"
fi

# Prompt directly
echo -n "Choose a CNI [$cni_default]: "
read input_cni
cni_choice=${input_cni:-"$cni_default"}

if [[ "$cni_choice" == "2" ]]; then
    echo -e "${YELLOW}Configuring Calico CNI...${NC}"
    safe_config_set "ansible:calico_iface" "$flannel_iface"
    safe_config_set "ansible:calico_tag" "v3.28.0"
    # Remove Cilium config if it exists
    if [[ "$has_cilium" == "true" ]]; then
        pulumi config rm ansible:cilium_iface 2>/dev/null || true
        pulumi config rm ansible:cilium_mode 2>/dev/null || true
        pulumi config rm ansible:cilium_tag 2>/dev/null || true
        pulumi config rm ansible:cilium_hubble 2>/dev/null || true
    fi
elif [[ "$cni_choice" == "3" ]]; then
    echo -e "${YELLOW}Configuring Cilium CNI...${NC}"
    safe_config_set "ansible:cilium_iface" "$flannel_iface"
    safe_config_set "ansible:cilium_mode" "native"
    safe_config_set "ansible:cilium_tag" "v1.16.0"
    safe_config_set "ansible:cilium_hubble" "true"
    # Remove Calico config if it exists
    if [[ "$has_calico" == "true" ]]; then
        pulumi config rm ansible:calico_iface 2>/dev/null || true
        pulumi config rm ansible:calico_tag 2>/dev/null || true
    fi
else
    echo -e "${YELLOW}Using default Flannel CNI${NC}"
    # Remove both Calico and Cilium configs if they exist
    if [[ "$has_calico" == "true" ]]; then
        pulumi config rm ansible:calico_iface 2>/dev/null || true
        pulumi config rm ansible:calico_tag 2>/dev/null || true
    fi
    if [[ "$has_cilium" == "true" ]]; then
        pulumi config rm ansible:cilium_iface 2>/dev/null || true
        pulumi config rm ansible:cilium_mode 2>/dev/null || true
        pulumi config rm ansible:cilium_tag 2>/dev/null || true
        pulumi config rm ansible:cilium_hubble 2>/dev/null || true
    fi
fi


# -----------------------------------------------------
# Deploy the Pulumi Stack
# -----------------------------------------------------
echo -e "\n${BLUE}=== Configuration Complete ===${NC}"
deploy_now_default="y"

# Prompt directly
echo -n "Would you like to deploy the stack now? (y/n) [$deploy_now_default]: "
read input_deploy_now
deploy_now=${input_deploy_now:-"$deploy_now_default"}

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