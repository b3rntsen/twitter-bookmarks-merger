#!/bin/bash
# Setup systemd service to ensure Docker Compose containers always run
# This ensures containers start on boot and restart if they fail

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SSH_KEY="${SSH_KEY:-~/.ssh/twitter-bookmarks-key.pem}"
SERVER_USER="${SERVER_USER:-ec2-user}"
SERVER_HOST="${SERVER_HOST:-13.62.72.70}"
PROJECT_DIR_REMOTE="/home/${SERVER_USER}/twitter-bookmarks"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔧 Setting up systemd service for Docker Compose${NC}"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
set -e

PROJECT_DIR="/home/ec2-user/twitter-bookmarks"
SERVICE_NAME="twitter-bookmarks"

# Create systemd service file
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << 'EOFSERVICE'
[Unit]
Description=Twitter Bookmarks Docker Compose Application
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ec2-user/twitter-bookmarks
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
TimeoutStartSec=0
Restart=on-failure
RestartSec=10

# Restart containers if they exit
ExecStartPost=/bin/bash -c 'while true; do sleep 300; /usr/bin/docker compose -f /home/ec2-user/twitter-bookmarks/docker-compose.prod.yml ps | grep -q "Up" || /usr/bin/docker compose -f /home/ec2-user/twitter-bookmarks/docker-compose.prod.yml up -d; done'

[Install]
WantedBy=multi-user.target
EOFSERVICE

# Create a better service file with proper restart handling
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << EOFSERVICE
[Unit]
Description=Twitter Bookmarks Docker Compose Application
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}
User=ec2-user
Group=ec2-user

# Start containers
ExecStart=/usr/bin/docker compose -f ${PROJECT_DIR}/docker-compose.prod.yml up -d

# Stop containers
ExecStop=/usr/bin/docker compose -f ${PROJECT_DIR}/docker-compose.prod.yml down

# Restart if failed
Restart=on-failure
RestartSec=10
TimeoutStartSec=300
TimeoutStopSec=30

# Environment
Environment="COMPOSE_PROJECT_NAME=twitter-bookmarks"

[Install]
WantedBy=multi-user.target
EOFSERVICE

# Create a watchdog script that ensures containers are running
sudo tee /usr/local/bin/${SERVICE_NAME}-watchdog.sh > /dev/null << 'EOFWATCHDOG'
#!/bin/bash
# Watchdog script to ensure containers are always running

PROJECT_DIR="/home/ec2-user/twitter-bookmarks"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.prod.yml"

cd "${PROJECT_DIR}"

# Check if containers are running
if ! docker compose -f "${COMPOSE_FILE}" ps | grep -q "Up"; then
    echo "$(date): Containers not running, starting them..."
    docker compose -f "${COMPOSE_FILE}" up -d
fi
EOFWATCHDOG

sudo chmod +x /usr/local/bin/${SERVICE_NAME}-watchdog.sh

# Create a timer to run the watchdog every 5 minutes
sudo tee /etc/systemd/system/${SERVICE_NAME}-watchdog.timer > /dev/null << EOFTIMER
[Unit]
Description=Twitter Bookmarks Watchdog Timer
After=docker.service

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
Unit=${SERVICE_NAME}-watchdog.service

[Install]
WantedBy=timers.target
EOFTIMER

# Create watchdog service
sudo tee /etc/systemd/system/${SERVICE_NAME}-watchdog.service > /dev/null << EOFSERVICE
[Unit]
Description=Twitter Bookmarks Container Watchdog
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/${SERVICE_NAME}-watchdog.sh
User=ec2-user
EOFSERVICE

# Reload systemd
sudo systemctl daemon-reload

# Enable and start the service
sudo systemctl enable ${SERVICE_NAME}.service
sudo systemctl enable ${SERVICE_NAME}-watchdog.timer

# Start the service if not already running
if ! sudo systemctl is-active --quiet ${SERVICE_NAME}.service; then
    sudo systemctl start ${SERVICE_NAME}.service
fi

# Start the watchdog timer
sudo systemctl start ${SERVICE_NAME}-watchdog.timer

echo "✅ Systemd service configured"
echo ""
echo "Service status:"
sudo systemctl status ${SERVICE_NAME}.service --no-pager -l || true
echo ""
echo "Watchdog timer status:"
sudo systemctl status ${SERVICE_NAME}-watchdog.timer --no-pager -l || true

echo ""
echo "Useful commands:"
echo "  sudo systemctl status ${SERVICE_NAME}.service"
echo "  sudo systemctl restart ${SERVICE_NAME}.service"
echo "  sudo systemctl stop ${SERVICE_NAME}.service"
echo "  sudo systemctl start ${SERVICE_NAME}.service"
ENDSSH

echo -e "${GREEN}✅ Systemd service setup complete${NC}"
