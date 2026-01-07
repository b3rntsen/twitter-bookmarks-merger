#!/bin/bash
# Optimize production server memory usage
# Run this on the EC2 instance (no git required)

set -e

PROJECT_DIR="${1:-/home/ec2-user/twitter-bookmarks}"

echo "🔧 Optimizing production server for memory conservation..."
echo "📁 Project directory: ${PROJECT_DIR}"

# 1. Setup swap (2GB)
echo "📦 Setting up swap..."
if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab
    echo "✅ Swap file created"
else
    echo "⚠️  Swap file already exists, skipping creation"
fi

# 2. Configure swappiness (less aggressive swapping)
echo "⚙️  Configuring swappiness..."
if ! grep -q "vm.swappiness" /etc/sysctl.conf; then
    echo "vm.swappiness=10" | sudo tee -a /etc/sysctl.conf
    sudo sysctl -w vm.swappiness=10
    echo "✅ Swappiness configured"
else
    echo "⚠️  Swappiness already configured"
fi

# 3. Kill any zombie Playwright processes
echo "🧹 Cleaning up zombie Playwright processes..."
sudo pkill -f headless_shell || true
sudo pkill -f chromium || true
sleep 2

# 4. Update .env file with Q_WORKERS=1 if not already set
echo "⚙️  Updating environment variables..."
cd "${PROJECT_DIR}"
if [ -f .env ]; then
    if ! grep -q "^Q_WORKERS=" .env; then
        echo "Q_WORKERS=1" >> .env
        echo "✅ Added Q_WORKERS=1 to .env"
    else
        # Update existing Q_WORKERS to 1
        sed -i 's/^Q_WORKERS=.*/Q_WORKERS=1/' .env
        echo "✅ Updated Q_WORKERS to 1 in .env"
    fi
    
    if ! grep -q "^Q_QUEUE_LIMIT=" .env; then
        echo "Q_QUEUE_LIMIT=10" >> .env
        echo "✅ Added Q_QUEUE_LIMIT=10 to .env"
    fi
else
    echo "⚠️  .env file not found, creating with defaults..."
    cat > .env << 'ENVEOF'
Q_WORKERS=1
Q_QUEUE_LIMIT=10
ENVEOF
    echo "✅ Created .env with Q_WORKERS=1"
fi

# 5. Restart Docker containers with new memory limits
echo "🔄 Restarting Docker containers with memory limits..."
docker compose -f docker-compose.prod.yml down --timeout 30 || true
docker compose -f docker-compose.prod.yml up -d

# 6. Wait for services to start
echo "⏳ Waiting for services to start..."
sleep 10

# 7. Verify memory usage
echo ""
echo "📊 Current memory status:"
free -h
echo ""
echo "📊 Docker container memory limits:"
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" || true

echo ""
echo "✅ Optimization complete!"
echo ""
echo "💡 Tips:"
echo "  - Monitor with: docker stats"
echo "  - Check logs: docker compose -f docker-compose.prod.yml logs -f qcluster"
echo "  - If still overloaded, consider upgrading to t3.medium (4GB RAM)"

