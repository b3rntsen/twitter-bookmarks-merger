#!/bin/bash
# Setup swap file on production server to handle memory pressure
# Run this on the EC2 instance

set -e

SWAP_SIZE="${1:-2G}"  # Default 2GB swap

echo "🔧 Setting up ${SWAP_SIZE} swap file..."

# Check if swap already exists
if [ -f /swapfile ]; then
    echo "⚠️  Swap file already exists. Removing old swap..."
    sudo swapoff /swapfile 2>/dev/null || true
    sudo rm /swapfile
fi

# Create swap file
echo "📦 Creating swap file..."
sudo fallocate -l ${SWAP_SIZE} /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make it permanent
if ! grep -q "/swapfile" /etc/fstab; then
    echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab
fi

# Set swappiness (lower = less aggressive swapping)
echo "⚙️  Configuring swappiness..."
echo "vm.swappiness=10" | sudo tee -a /etc/sysctl.conf
sudo sysctl -w vm.swappiness=10

# Verify
echo "✅ Swap setup complete!"
echo "📊 Current swap status:"
free -h
swapon --show

