#!/bin/bash
set -e

# Colors for better output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Pulumi Proxmox K3s Bootstrap ===${NC}"
echo -e "${BLUE}This script will set up your environment to use the Pulumi Proxmox K3s project${NC}"
echo -e "${BLUE}==================================${NC}\n"

# Check if Python 3.8+ is installed
python_version=$(python3 --version 2>&1 | awk '{print $2}')
py_major=$(echo "$python_version" | cut -d. -f1)
py_minor=$(echo "$python_version" | cut -d. -f2)

echo -e "${YELLOW}Checking Python version...${NC}"
if [[ "$py_major" -lt 3 ]] || [[ "$py_major" -eq 3 && "$py_minor" -lt 8 ]]; then
    echo -e "${RED}Python 3.8 or higher is required. Found: Python $python_version${NC}"
    echo -e "${YELLOW}Please install Python 3.8+ and try again${NC}"
    exit 1
else
    echo -e "${GREEN}Python $python_version detected - OK${NC}"
fi

# Check if venv module is available
echo -e "${YELLOW}Checking venv module...${NC}"
if ! python3 -m venv --help > /dev/null 2>&1; then
    echo -e "${RED}Python venv module is not available.${NC}"
    echo -e "${YELLOW}Please install it with: sudo apt install python3-venv (Ubuntu/Debian) or equivalent for your OS${NC}"
    exit 1
else
    echo -e "${GREEN}Python venv module detected - OK${NC}"
fi

# Check if pulumi is installed
echo -e "${YELLOW}Checking Pulumi CLI...${NC}"
if ! command -v pulumi &> /dev/null; then
    echo -e "${RED}Pulumi CLI not found.${NC}"
    echo -e "${YELLOW}Would you like to install Pulumi CLI? (y/n)${NC}"
    read -r install_pulumi
    if [[ "$install_pulumi" == "y" ]]; then
        echo -e "${BLUE}Installing Pulumi CLI...${NC}"
        curl -fsSL https://get.pulumi.com | sh
        source ~/.bashrc
    else
        echo -e "${YELLOW}Please install Pulumi CLI manually: https://www.pulumi.com/docs/install/${NC}"
        echo -e "${YELLOW}Then run this script again.${NC}"
        exit 1
    fi
else
    pulumi_version=$(pulumi version)
    echo -e "${GREEN}Pulumi CLI detected: $pulumi_version - OK${NC}"
fi

# Check if ansible is installed
echo -e "${YELLOW}Checking Ansible...${NC}"
if ! command -v ansible &> /dev/null; then
    echo -e "${RED}Ansible not found.${NC}"
    echo -e "${YELLOW}Would you like to install Ansible? (y/n)${NC}"
    read -r install_ansible
    if [[ "$install_ansible" == "y" ]]; then
        echo -e "${BLUE}Installing Ansible...${NC}"
        sudo apt update
        sudo apt install -y ansible
    else
        echo -e "${YELLOW}Please install Ansible manually: 'sudo apt install ansible' (Ubuntu/Debian) or equivalent for your OS${NC}"
        echo -e "${YELLOW}You will need Ansible installed to run the k3s installation.${NC}"
    fi
else
    ansible_version=$(ansible --version | head -n1)
    echo -e "${GREEN}Ansible detected: $ansible_version - OK${NC}"
fi

# Create virtual environment if it doesn't exist
echo -e "${YELLOW}Setting up virtual environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}Virtual environment created${NC}"
else
    echo -e "${GREEN}Virtual environment already exists${NC}"
fi

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source venv/bin/activate

# Install requirements
echo -e "${YELLOW}Installing Python dependencies...${NC}"
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo -e "${GREEN}Dependencies installed successfully${NC}"
else
    echo -e "${RED}requirements.txt not found${NC}"
    echo -e "${YELLOW}Creating basic requirements.txt...${NC}"
    cat > requirements.txt << EOF
pulumi>=3.0.0,<4.0.0
pulumi-proxmoxve>=2.0.0
paramiko>=3.0.0
EOF
    pip install -r requirements.txt
    echo -e "${GREEN}Basic dependencies installed successfully${NC}"
fi

# Check if git is properly configured
echo -e "${YELLOW}Checking git configuration...${NC}"
if ! git config --get user.name > /dev/null || ! git config --get user.email > /dev/null; then
    echo -e "${RED}Git user not configured.${NC}"
    echo -e "${YELLOW}Please configure your git user with:${NC}"
    echo -e "${YELLOW}  git config --global user.name \"Your Name\"${NC}"
    echo -e "${YELLOW}  git config --global user.email \"your.email@example.com\"${NC}"
else
    git_user=$(git config --get user.name)
    git_email=$(git config --get user.email)
    echo -e "${GREEN}Git configured for: $git_user <$git_email> - OK${NC}"
fi

# Create directories if they don't exist
echo -e "${YELLOW}Creating project structure...${NC}"
mkdir -p proxmox
mkdir -p scripts
touch proxmox/__init__.py
touch scripts/__init__.py

echo -e "\n${GREEN}===========================================${NC}"
echo -e "${GREEN}✓ Environment setup completed successfully!${NC}"
echo -e "${GREEN}===========================================${NC}"
echo -e "\n${BLUE}Next steps:${NC}"
echo -e "  ${YELLOW}1. Run the setup script:${NC} chmod +x setup-example.sh && ./setup-example.sh"
echo -e "  ${YELLOW}2. The setup script will automatically activate the virtual environment and guide you through configuration${NC}"
echo -e "  ${YELLOW}3. Or for manual setup, activate the environment:${NC} source venv/bin/activate"
echo -e "  ${YELLOW}4. And configure Pulumi manually:${NC} pulumi config set proxmox:username your-username@pam"
echo -e "\n${BLUE}Happy Kubernetes clustering!${NC}" 