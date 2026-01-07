#!/bin/bash
# Install rsync on production server

set -e

SSH_KEY="${SSH_KEY:-$HOME/.ssh/twitter-bookmarks-key.pem}"
SERVER_USER="${SERVER_USER:-ec2-user}"
SERVER_HOST="${SERVER_HOST:-13.62.72.70}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}📦 Installing rsync on production server${NC}"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
    # Check if rsync is already installed
    if command -v rsync &> /dev/null; then
        echo "✅ rsync is already installed"
        rsync --version | head -1
        exit 0
    fi
    
    # Detect OS and install rsync
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
    else
        echo "❌ Cannot detect OS"
        exit 1
    fi
    
    echo "Detected OS: $OS"
    
    case $OS in
        amzn|amazon)
            echo "Installing rsync on Amazon Linux..."
            sudo yum update -y
            sudo yum install -y rsync
            ;;
        ubuntu|debian)
            echo "Installing rsync on Ubuntu/Debian..."
            sudo apt-get update
            sudo apt-get install -y rsync
            ;;
        *)
            echo "❌ Unsupported OS: $OS"
            echo "Please install rsync manually"
            exit 1
            ;;
    esac
    
    # Verify installation
    if command -v rsync &> /dev/null; then
        echo "✅ rsync installed successfully"
        rsync --version | head -1
    else
        echo "❌ rsync installation failed"
        exit 1
    fi
ENDSSH

echo -e "${GREEN}✅ rsync installation complete${NC}"
