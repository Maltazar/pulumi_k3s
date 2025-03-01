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

# Skip prompts for existing configuration values
# Set to 1 to only be prompted for values that don't exist in the Pulumi config
# Example: SKIP_EXISTING_CONFIG=1 ./setup-example.sh
SKIP_EXISTING_CONFIG=${SKIP_EXISTING_CONFIG:-0}

debug_log() {
    if [ "$DEBUG" -eq 1 ]; then
        echo -e "${GRAY}[DEBUG] $1${NC}" >&2
    fi
}

echo -e "${BLUE}=== Pulumi Proxmox K3s Deployment Example ===${NC}"
echo -e "${BLUE}This script will set up a complete Pulumi Proxmox K3s deployment${NC}"
echo -e "${BLUE}=============================================${NC}\n"

# Show if we're skipping existing config prompts
if [ "$SKIP_EXISTING_CONFIG" -eq 1 ]; then
    echo -e "${YELLOW}Running in skip mode - will only prompt for missing configuration values${NC}\n"
fi

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

# Function to determine whether to prompt for a value
# Returns 0 (true) if should prompt, 1 (false) if should skip prompt
should_prompt() {
    local key=$1
    
    # Always prompt if SKIP_EXISTING_CONFIG is disabled
    if [ "$SKIP_EXISTING_CONFIG" -ne 1 ]; then
        return 0
    fi
    
    # If SKIP_EXISTING_CONFIG is enabled, only prompt if the config doesn't exist
    if pulumi config get "$key" &>/dev/null; then
        debug_log "Skipping prompt for existing config: $key"
        return 1
    else
        debug_log "Will prompt for missing config: $key"
        return 0
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

# Proxmox endpoint
stored_endpoint=$(get_config_or_default "proxmox:endpoint" "")
if should_prompt "proxmox:endpoint"; then
    echo -n "Proxmox endpoint URL [$stored_endpoint]: "
    read input_endpoint
    proxmox_endpoint=${input_endpoint:-"$stored_endpoint"}
else
    proxmox_endpoint="$stored_endpoint"
    echo -e "Using existing Proxmox endpoint URL: ${GREEN}$proxmox_endpoint${NC}"
fi

# Proxmox username
stored_username=$(get_config_or_default "proxmox:username" "")
if should_prompt "proxmox:username"; then
    echo -n "Proxmox username (e.g., user@pam) [$stored_username]: "
    read input_username
    proxmox_username=${input_username:-"$stored_username"}
else
    proxmox_username="$stored_username"
    echo -e "Using existing Proxmox username: ${GREEN}$proxmox_username${NC}"
fi

# Check that username is not empty
while [ -z "$proxmox_username" ]; do
    echo -e "${RED}Username cannot be empty${NC}"
    echo -n "Proxmox username (e.g., user@pam): "
    read proxmox_username
done

# Get Proxmox password - special handling for secrets
if should_prompt "proxmox:password" && ! pulumi config get proxmox:password &>/dev/null; then
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
else
    if pulumi config get proxmox:password &>/dev/null; then
        echo -e "Using existing secret for ${GREEN}proxmox:password${NC}"
    fi
    proxmox_password=""
fi

# Proxmox node
stored_node=$(get_config_or_default "proxmox:node" "")
if should_prompt "proxmox:node"; then
    echo -n "Proxmox node name [$stored_node]: "
    read input_node
    proxmox_node=${input_node:-"$stored_node"}
else
    proxmox_node="$stored_node"
    echo -e "Using existing Proxmox node name: ${GREEN}$proxmox_node${NC}"
fi

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
if should_prompt "vm:template"; then
    echo -n "VM template ID [$stored_template]: "
    read input_template
    vm_template=${input_template:-"$stored_template"}
else
    vm_template="$stored_template"
    echo -e "Using existing VM template ID: ${GREEN}$vm_template${NC}"
fi

# Check that template is not empty
while [ -z "$vm_template" ]; do
    echo -e "${RED}Template ID cannot be empty${NC}"
    echo -n "VM template ID: "
    read vm_template
done

# VM SSH Settings
echo -e "${YELLOW}Configure SSH access to the VMs:${NC}"
stored_ssh_user=$(get_config_or_default "vm:ssh_user" "")
if should_prompt "vm:ssh_user"; then
    echo -n "SSH username [$stored_ssh_user]: "
    read input_ssh_user
    ssh_user=${input_ssh_user:-"$stored_ssh_user"}
else
    ssh_user="$stored_ssh_user"
    echo -e "Using existing SSH username: ${GREEN}$ssh_user${NC}"
fi

stored_ssh_private_key_path=$(get_config_or_default "vm:ssh_private_key_path" "$HOME/.ssh/id_rsa")
if should_prompt "vm:ssh_private_key_path"; then
    echo -n "SSH private key path [$stored_ssh_private_key_path]: "
    read input_ssh_private_key_path
    ssh_private_key_path=${input_ssh_private_key_path:-"$stored_ssh_private_key_path"}
else
    ssh_private_key_path="$stored_ssh_private_key_path"
    echo -e "Using existing SSH private key path: ${GREEN}$ssh_private_key_path${NC}"
fi

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

# Check if the key requires a passphrase
if should_prompt "vm:ssh_key_passphrase"; then
    echo -e "${YELLOW}Does your SSH key require a passphrase? (y/n)${NC}"
    read -r has_passphrase
    if [[ "$has_passphrase" == "y" ]]; then
        echo -n "Enter SSH key passphrase: "
        read -s ssh_key_passphrase
        echo
        
        # Set the passphrase in Pulumi config as a secret
        safe_config_set "vm:ssh_key_passphrase" "$ssh_key_passphrase" "true"
    fi
else
    if pulumi config get vm:ssh_key_passphrase &>/dev/null; then
        echo -e "Using existing secret for ${GREEN}vm:ssh_key_passphrase${NC}"
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
if should_prompt "vm:ssh_public_key"; then
    echo -e "SSH public key (can be a file path like ~/.ssh/id_rsa.pub or the actual key content)"
    echo -n "SSH public key [$display_key]: "
    read input_ssh_public_key
    ssh_public_key=${input_ssh_public_key:-"$stored_ssh_public_key"}
else
    ssh_public_key="$stored_ssh_public_key"
    echo -e "Using existing SSH public key: ${GREEN}${display_key}${NC}"
fi

# Admin user configuration
echo -e "${YELLOW}Configure VM admin user (optional):${NC}"
stored_create_admin=$(get_config_or_default "vm:create_admin_user" "false")
if [[ "$stored_create_admin" == "true" ]]; then
    stored_create_admin="y"
else
    stored_create_admin="n"
fi

if should_prompt "vm:create_admin_user"; then
    echo -n "Create a sudo admin user? (y/n) [$stored_create_admin]: "
    read input_create_admin
    create_admin=${input_create_admin:-"$stored_create_admin"}
else
    create_admin="$stored_create_admin"
    echo -e "Using existing admin user setting: ${GREEN}$create_admin${NC}"
fi

if [[ "$create_admin" == "y" ]]; then
    safe_config_set "vm:create_admin_user" "true"
    
    # Admin username
    stored_admin_username=$(get_config_or_default "vm:admin_username" "admin")
    if should_prompt "vm:admin_username"; then
        echo -n "Admin username [$stored_admin_username]: "
        read input_admin_username
        admin_username=${input_admin_username:-"$stored_admin_username"}
    else
        admin_username="$stored_admin_username"
        echo -e "Using existing admin username: ${GREEN}$admin_username${NC}"
    fi
    
    # Admin password (optional)
    if should_prompt "vm:admin_password"; then
        echo -e "${YELLOW}Set an admin password? (y/n)${NC}"
        read -r set_admin_password
        if [[ "$set_admin_password" == "y" ]]; then
            echo -n "Admin password: "
            read -s admin_password
            echo
            
            # Set the admin password in Pulumi config as a secret
            safe_config_set "vm:admin_password" "$admin_password" "true"
        fi
    else
        if pulumi config get vm:admin_password &>/dev/null; then
            echo -e "Using existing secret for ${GREEN}vm:admin_password${NC}"
        fi
    fi
    
    # Admin SSH key (optional - defaults to the same as the VM SSH key)
    stored_admin_ssh_key=$(get_config_or_default "vm:admin_ssh_key" "$ssh_public_key")
    if [ ${#stored_admin_ssh_key} -gt 40 ]; then
        # If key is long, only show beginning
        display_admin_key="${stored_admin_ssh_key:0:40}..."
    else
        display_admin_key="$stored_admin_ssh_key"
    fi
    
    if should_prompt "vm:admin_ssh_key"; then
        echo -e "${YELLOW}Use same SSH key for admin user? (y/n) [y]:${NC}"
        read -r use_same_key
        if [[ "$use_same_key" != "y" && "$use_same_key" != "" ]]; then
            echo -e "Admin SSH public key (can be a file path like ~/.ssh/id_rsa.pub or the actual key content)"
            echo -n "Admin SSH public key: "
            read admin_ssh_key
            safe_config_set "vm:admin_ssh_key" "$admin_ssh_key"
        else
            # Use the same SSH key
            safe_config_set "vm:admin_ssh_key" "$ssh_public_key"
        fi
    else
        echo -e "Using existing admin SSH key: ${GREEN}${display_admin_key}${NC}"
    fi
    
    # Set admin username
    safe_config_set "vm:admin_username" "$admin_username"
else
    safe_config_set "vm:create_admin_user" "false"
    # Remove any existing admin user config
    pulumi config rm vm:admin_username 2>/dev/null || true
    pulumi config rm vm:admin_password 2>/dev/null || true
    pulumi config rm vm:admin_ssh_key 2>/dev/null || true
fi

# VM Resources
echo -e "${YELLOW}Configure VM resources:${NC}"
stored_cores=$(get_config_or_default "vm:cores" "")
if should_prompt "vm:cores"; then
    echo -n "Default VM cores [$stored_cores]: "
    read input_cores
    vm_cores=${input_cores:-"$stored_cores"}
else
    vm_cores="$stored_cores"
    echo -e "Using existing VM cores: ${GREEN}$vm_cores${NC}"
fi

stored_memory=$(get_config_or_default "vm:memory" "")
if should_prompt "vm:memory"; then
    echo -n "Default VM memory in MB [$stored_memory]: "
    read input_memory
    vm_memory=${input_memory:-"$stored_memory"}
else
    vm_memory="$stored_memory"
    echo -e "Using existing VM memory: ${GREEN}$vm_memory${NC}"
fi

stored_disk_size=$(get_config_or_default "vm:disk_size" "")
if should_prompt "vm:disk_size"; then
    echo -n "Default VM disk size [$stored_disk_size]: "
    read input_disk_size
    vm_disk_size=${input_disk_size:-"$stored_disk_size"}
else
    vm_disk_size="$stored_disk_size"
    echo -e "Using existing VM disk size: ${GREEN}$vm_disk_size${NC}"
fi

stored_disk_storage=$(get_config_or_default "vm:disk_storage" "")
if should_prompt "vm:disk_storage"; then
    echo -n "Default VM disk storage location [$stored_disk_storage]: "
    read input_disk_storage
    vm_disk_storage=${input_disk_storage:-"$stored_disk_storage"}
else
    vm_disk_storage="$stored_disk_storage"
    echo -e "Using existing VM disk storage: ${GREEN}$vm_disk_storage${NC}"
fi

stored_network_bridge=$(get_config_or_default "vm:network_bridge" "")
if should_prompt "vm:network_bridge"; then
    echo -n "VM network bridge [$stored_network_bridge]: "
    read input_network_bridge
    vm_network_bridge=${input_network_bridge:-"$stored_network_bridge"}
else
    vm_network_bridge="$stored_network_bridge"
    echo -e "Using existing VM network bridge: ${GREEN}$vm_network_bridge${NC}"
fi

# Add VLAN tag prompt (new)
stored_vlan_tag=$(get_config_or_default "vm:vlan_tag" "")
if should_prompt "vm:vlan_tag"; then
    echo -n "VM network VLAN tag (leave empty for no VLAN) [$stored_vlan_tag]: "
    read input_vlan_tag
    vm_vlan_tag=${input_vlan_tag:-"$stored_vlan_tag"}
else
    vm_vlan_tag="$stored_vlan_tag"
    if [ -n "$vm_vlan_tag" ]; then
        echo -e "Using existing VM VLAN tag: ${GREEN}$vm_vlan_tag${NC}"
    else
        echo -e "No VLAN tag configured"
    fi
fi

# VM ID range (optional)
echo -e "${YELLOW}VM ID range (optional - leave empty to let Proxmox assign IDs automatically):${NC}"
stored_vm_id_min=$(get_config_or_default "vm:vm_id_min" "")
if should_prompt "vm:vm_id_min"; then
    echo -n "Minimum VM ID (e.g., 1000) [$stored_vm_id_min]: "
    read input_vm_id_min
    vm_id_min=${input_vm_id_min:-"$stored_vm_id_min"}
else
    vm_id_min="$stored_vm_id_min"
    if [ -n "$vm_id_min" ]; then
        echo -e "Using existing minimum VM ID: ${GREEN}$vm_id_min${NC}"
    else
        echo -e "No minimum VM ID set - Proxmox will assign automatically"
    fi
fi

stored_vm_id_max=$(get_config_or_default "vm:vm_id_max" "")
if should_prompt "vm:vm_id_max"; then
    echo -n "Maximum VM ID (e.g., 1050) [$stored_vm_id_max]: "
    read input_vm_id_max
    vm_id_max=${input_vm_id_max:-"$stored_vm_id_max"}
else
    vm_id_max="$stored_vm_id_max"
    if [ -n "$vm_id_max" ]; then
        echo -e "Using existing maximum VM ID: ${GREEN}$vm_id_max${NC}"
    else
        echo -e "No maximum VM ID set - Proxmox will assign automatically"
    fi
fi

# Set VM configuration
safe_config_set "vm:template" "$vm_template"
safe_config_set "vm:cores" "$vm_cores"
safe_config_set "vm:memory" "$vm_memory"
safe_config_set "vm:disk_size" "$vm_disk_size"
safe_config_set "vm:disk_storage" "$vm_disk_storage"
safe_config_set "vm:ssh_user" "$ssh_user"
safe_config_set "vm:ssh_public_key" "$ssh_public_key"
safe_config_set "vm:ssh_private_key_path" "$ssh_private_key_path"
safe_config_set "vm:network_bridge" "$vm_network_bridge"
if [ -n "$vm_vlan_tag" ]; then
    safe_config_set "vm:vlan_tag" "$vm_vlan_tag"
else
    # Remove VLAN tag if it exists but is now empty
    pulumi config rm vm:vlan_tag 2>/dev/null || true
fi

# Set VM ID range if provided
if [ -n "$vm_id_min" ]; then
    safe_config_set "vm:vm_id_min" "$vm_id_min"
fi
if [ -n "$vm_id_max" ]; then
    safe_config_set "vm:vm_id_max" "$vm_id_max"
fi

# -----------------------------------------------------
# Configure K3s Cluster Settings
# -----------------------------------------------------
echo -e "${BLUE}Configuring K3s cluster settings...${NC}"

# Master nodes
stored_master_count=$(get_config_or_default "k3s:master_count" "")
if should_prompt "k3s:master_count"; then
    echo -n "Number of master nodes [$stored_master_count]: "
    read input_master_count
    master_count=${input_master_count:-"$stored_master_count"}
else
    master_count="$stored_master_count"
    echo -e "Using existing master count: ${GREEN}$master_count${NC}"
fi

# Worker nodes
stored_worker_count=$(get_config_or_default "k3s:worker_count" "")
if should_prompt "k3s:worker_count"; then
    echo -n "Number of worker nodes [$stored_worker_count]: "
    read input_worker_count
    worker_count=${input_worker_count:-"$stored_worker_count"}
else
    worker_count="$stored_worker_count"
    echo -e "Using existing worker count: ${GREEN}$worker_count${NC}"
fi

# Name prefixes
stored_master_prefix=$(get_config_or_default "k3s:master_name_prefix" "")
if should_prompt "k3s:master_name_prefix"; then
    echo -n "Master node name prefix [$stored_master_prefix]: "
    read input_master_prefix
    master_prefix=${input_master_prefix:-"$stored_master_prefix"}
else
    master_prefix="$stored_master_prefix"
    echo -e "Using existing master prefix: ${GREEN}$master_prefix${NC}"
fi

stored_worker_prefix=$(get_config_or_default "k3s:worker_name_prefix" "")
if should_prompt "k3s:worker_name_prefix"; then
    echo -n "Worker node name prefix [$stored_worker_prefix]: "
    read input_worker_prefix
    worker_prefix=${input_worker_prefix:-"$stored_worker_prefix"}
else
    worker_prefix="$stored_worker_prefix"
    echo -e "Using existing worker prefix: ${GREEN}$worker_prefix${NC}"
fi

# Resource allocation
stored_master_cores=$(get_config_or_default "k3s:master_cores" "")
if should_prompt "k3s:master_cores"; then
    echo -n "Master node cores [$stored_master_cores]: "
    read input_master_cores
    master_cores=${input_master_cores:-"$stored_master_cores"}
else
    master_cores="$stored_master_cores"
    echo -e "Using existing master cores: ${GREEN}$master_cores${NC}"
fi

stored_master_memory=$(get_config_or_default "k3s:master_memory" "")
if should_prompt "k3s:master_memory"; then
    echo -n "Master node memory in MB [$stored_master_memory]: "
    read input_master_memory
    master_memory=${input_master_memory:-"$stored_master_memory"}
else
    master_memory="$stored_master_memory"
    echo -e "Using existing master memory: ${GREEN}$master_memory${NC}"
fi

stored_worker_cores=$(get_config_or_default "k3s:worker_cores" "")
if should_prompt "k3s:worker_cores"; then
    echo -n "Worker node cores [$stored_worker_cores]: "
    read input_worker_cores
    worker_cores=${input_worker_cores:-"$stored_worker_cores"}
else
    worker_cores="$stored_worker_cores"
    echo -e "Using existing worker cores: ${GREEN}$worker_cores${NC}"
fi

stored_worker_memory=$(get_config_or_default "k3s:worker_memory" "")
if should_prompt "k3s:worker_memory"; then
    echo -n "Worker node memory in MB [$stored_worker_memory]: "
    read input_worker_memory
    worker_memory=${input_worker_memory:-"$stored_worker_memory"}
else
    worker_memory="$stored_worker_memory"
    echo -e "Using existing worker memory: ${GREEN}$worker_memory${NC}"
fi

# K3s version
stored_k3s_version=$(get_config_or_default "k3s:version" "")
if should_prompt "k3s:version"; then
    echo -n "K3s version [$stored_k3s_version]: "
    read input_k3s_version
    k3s_version=${input_k3s_version:-"$stored_k3s_version"}
else
    k3s_version="$stored_k3s_version"
    echo -e "Using existing K3s version: ${GREEN}$k3s_version${NC}"
fi

# Static IP configuration
stored_use_static_ips=$(get_config_or_default "k3s:use_static_ips" "")

# Convert true/false to y/n for user interaction if needed
if [[ "$stored_use_static_ips" == "true" ]]; then
    stored_use_static_ips="y"
elif [[ "$stored_use_static_ips" == "false" ]]; then
    stored_use_static_ips="n"
fi

if should_prompt "k3s:use_static_ips"; then
    echo -n "Do you want to use static IPs for the VMs? (y/n) [$stored_use_static_ips]: "
    read input_use_static_ips
    use_static_ips=${input_use_static_ips:-"$stored_use_static_ips"}
else
    use_static_ips="$stored_use_static_ips"
    echo -e "Using existing static IP setting: ${GREEN}$use_static_ips${NC}"
fi

if [[ "$use_static_ips" == "y" ]]; then
    safe_config_set "k3s:use_static_ips" "true"
    
    stored_ip_network=$(get_config_or_default "k3s:ip_network" "")
    if should_prompt "k3s:ip_network"; then
        echo -n "IP network CIDR [$stored_ip_network]: "
        read input_ip_network
        ip_network=${input_ip_network:-"$stored_ip_network"}
    else
        ip_network="$stored_ip_network"
        echo -e "Using existing IP network: ${GREEN}$ip_network${NC}"
    fi
    
    stored_ip_gateway=$(get_config_or_default "k3s:ip_gateway" "")
    if should_prompt "k3s:ip_gateway"; then
        echo -n "IP gateway [$stored_ip_gateway]: "
        read input_ip_gateway
        ip_gateway=${input_ip_gateway:-"$stored_ip_gateway"}
    else
        ip_gateway="$stored_ip_gateway"
        echo -e "Using existing IP gateway: ${GREEN}$ip_gateway${NC}"
    fi
    
    stored_ip_start=$(get_config_or_default "k3s:ip_start" "")
    if should_prompt "k3s:ip_start"; then
        echo -n "Starting IP offset (e.g., 100 for 192.168.1.100) [$stored_ip_start]: "
        read input_ip_start
        ip_start=${input_ip_start:-"$stored_ip_start"}
    else
        ip_start="$stored_ip_start"
        echo -e "Using existing IP start: ${GREEN}$ip_start${NC}"
    fi
    
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
if should_prompt "k3s:install_args"; then
    echo -n "K3s install args [$stored_install_args]: "
    read input_install_args
    install_args=${input_install_args:-"$stored_install_args"}
else
    install_args="$stored_install_args"
    echo -e "Using existing K3s install args: ${GREEN}$install_args${NC}"
fi

safe_config_set "k3s:install_args" "$install_args"

# -----------------------------------------------------
# Configure Ansible Settings
# -----------------------------------------------------
echo -e "${BLUE}Configuring Ansible settings...${NC}"

stored_repo_url=$(get_config_or_default "ansible:repo_url" "")
if should_prompt "ansible:repo_url"; then
    echo -n "Ansible repository URL [$stored_repo_url]: "
    read input_repo_url
    ansible_repo_url=${input_repo_url:-"$stored_repo_url"}
else
    ansible_repo_url="$stored_repo_url"
    echo -e "Using existing Ansible repo URL: ${GREEN}$ansible_repo_url${NC}"
fi

stored_repo_branch=$(get_config_or_default "ansible:repo_branch" "")
if should_prompt "ansible:repo_branch"; then
    echo -n "Ansible repository branch [$stored_repo_branch]: "
    read input_repo_branch
    ansible_repo_branch=${input_repo_branch:-"$stored_repo_branch"}
else
    ansible_repo_branch="$stored_repo_branch"
    echo -e "Using existing Ansible repo branch: ${GREEN}$ansible_repo_branch${NC}"
fi

stored_local_path=$(get_config_or_default "ansible:local_path" "")
if should_prompt "ansible:local_path"; then
    echo -n "Ansible local path [$stored_local_path]: "
    read input_local_path
    ansible_local_path=${input_local_path:-"$stored_local_path"}
else
    ansible_local_path="$stored_local_path"
    echo -e "Using existing Ansible local path: ${GREEN}$ansible_local_path${NC}"
fi

stored_cache_repo=$(get_config_or_default "ansible:cache_repo" "")

# Convert true/false to y/n for user interaction if needed
if [[ "$stored_cache_repo" == "true" ]]; then
    stored_cache_repo="y"
elif [[ "$stored_cache_repo" == "false" ]]; then
    stored_cache_repo="n"
fi

if should_prompt "ansible:cache_repo"; then
    echo -n "Cache the Ansible repository locally? (y/n) [$stored_cache_repo]: "
    read input_cache_repo
    ansible_cache_repo=${input_cache_repo:-"$stored_cache_repo"}
else
    ansible_cache_repo="$stored_cache_repo"
    echo -e "Using existing Ansible cache repo setting: ${GREEN}$ansible_cache_repo${NC}"
fi

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
if should_prompt "ansible:system_timezone"; then
    echo -n "System timezone [$stored_timezone]: "
    read input_timezone
    system_timezone=${input_timezone:-"$stored_timezone"}
else
    system_timezone="$stored_timezone"
    echo -e "Using existing system timezone: ${GREEN}$system_timezone${NC}"
fi

safe_config_set "ansible:system_timezone" "$system_timezone"

# Load balancer IP range
stored_lb_range=$(get_config_or_default "ansible:metal_lb_ip_range" "")
if should_prompt "ansible:metal_lb_ip_range"; then
    echo -n "MetalLB IP range for LoadBalancer services [$stored_lb_range]: "
    read input_lb_range
    metal_lb_ip_range=${input_lb_range:-"$stored_lb_range"}
else
    metal_lb_ip_range="$stored_lb_range"
    echo -e "Using existing MetalLB IP range: ${GREEN}$metal_lb_ip_range${NC}"
fi

safe_config_set "ansible:metal_lb_ip_range" "$metal_lb_ip_range"

# Network interface
stored_iface=$(get_config_or_default "ansible:flannel_iface" "")
if should_prompt "ansible:flannel_iface"; then
    echo -n "Network interface for K3s [$stored_iface]: "
    read input_iface
    flannel_iface=${input_iface:-"$stored_iface"}
else
    flannel_iface="$stored_iface"
    echo -e "Using existing network interface: ${GREEN}$flannel_iface${NC}"
fi

safe_config_set "ansible:flannel_iface" "$flannel_iface"

# Pod CIDR
stored_cidr=$(get_config_or_default "ansible:cluster_cidr" "")
if should_prompt "ansible:cluster_cidr"; then
    echo -n "Pod CIDR range [$stored_cidr]: "
    read input_cidr
    cluster_cidr=${input_cidr:-"$stored_cidr"}
else
    cluster_cidr="$stored_cidr"
    echo -e "Using existing Pod CIDR range: ${GREEN}$cluster_cidr${NC}"
fi

safe_config_set "ansible:cluster_cidr" "$cluster_cidr"

# Add API server endpoint configuration (new)
stored_api_endpoint=$(get_config_or_default "ansible:apiserver_endpoint" "")
if should_prompt "ansible:apiserver_endpoint"; then
    echo -e "${YELLOW}K3s API Server Endpoint (Virtual IP for Kubernetes API):${NC}"
    echo -e "This will be used as the virtual IP for accessing the Kubernetes API server"
    echo -n "API server endpoint [$stored_api_endpoint]: "
    read input_api_endpoint
    api_endpoint=${input_api_endpoint:-"$stored_api_endpoint"}
else
    api_endpoint="$stored_api_endpoint"
    if [ -n "$api_endpoint" ]; then
        echo -e "Using existing API server endpoint: ${GREEN}$api_endpoint${NC}"
    else
        echo -e "${RED}No API server endpoint configured - this is required for HA clusters${NC}"
    fi
fi
safe_config_set "ansible:apiserver_endpoint" "$api_endpoint"

# Generate and save k3s_token if it doesn't exist
stored_k3s_token=$(get_config_or_default "ansible:k3s_token" "")
if [ -z "$stored_k3s_token" ]; then
    echo -e "${YELLOW}Generating secure K3s token...${NC}"
    # Generate a secure random token
    k3s_token=$(tr -dc 'a-zA-Z0-9' < /dev/urandom | fold -w 32 | head -n 1)
    safe_config_set --secret "ansible:k3s_token" "$k3s_token"
    echo -e "${GREEN}K3s token generated and saved securely in Pulumi configuration${NC}"
else
    echo -e "${GREEN}Using existing K3s token from configuration${NC}"
fi

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

# Define a pseudo key for tracking CNI choice
cni_key="ansible:cni_choice"

# Prompt directly
if should_prompt "$cni_key"; then
    echo -n "Choose a CNI [$cni_default]: "
    read input_cni
    cni_choice=${input_cni:-"$cni_default"}
else
    cni_choice="$cni_default"
    if [[ "$cni_choice" == "1" ]]; then
        cni_name="Flannel (default)"
    elif [[ "$cni_choice" == "2" ]]; then
        cni_name="Calico"
    elif [[ "$cni_choice" == "3" ]]; then
        cni_name="Cilium"
    fi
    echo -e "Using existing CNI: ${GREEN}$cni_name${NC}"
fi

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

# Define a pseudo key for deployment choice
deploy_key="deployment:deploy_now"

# Prompt directly
if should_prompt "$deploy_key"; then
    echo -n "Would you like to deploy the stack now? (y/n) [$deploy_now_default]: "
    read input_deploy_now
    deploy_now=${input_deploy_now:-"$deploy_now_default"}
else
    deploy_now="$deploy_now_default"
    echo -e "Using default deployment choice: ${GREEN}Yes${NC}"
fi

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