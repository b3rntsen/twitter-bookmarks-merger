#!/bin/bash
# Server cleanup script - frees disk space on the production server
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SSH_KEY="${SSH_KEY:-~/.ssh/twitter-bookmarks-key.pem}"
SERVER_USER="${SERVER_USER:-ec2-user}"
SERVER_HOST="${SERVER_HOST:-13.62.72.70}"

echo -e "${GREEN}=== Server Cleanup ===${NC}"
echo ""

# Check current disk usage
echo -e "${YELLOW}Current disk usage:${NC}"
ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" "df -h /"
echo ""

# Docker cleanup
echo -e "${YELLOW}Cleaning Docker resources...${NC}"
ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
echo "Removing stopped containers..."
docker container prune -f

echo "Removing unused images..."
docker image prune -af

echo "Removing build cache..."
docker builder prune -af

echo "Removing unused volumes (keeping active ones)..."
docker volume prune -f

echo ""
echo "Docker system usage after cleanup:"
docker system df
ENDSSH

echo ""

# Clean old log files
echo -e "${YELLOW}Cleaning old log files...${NC}"
ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
# Remove old Docker logs (older than 7 days)
sudo find /var/lib/docker/containers -name "*.log" -mtime +7 -delete 2>/dev/null || true

# Truncate current Docker logs to last 1000 lines
for log in /var/lib/docker/containers/*/*.log; do
    if [ -f "$log" ]; then
        sudo tail -1000 "$log" > /tmp/truncated.log && sudo mv /tmp/truncated.log "$log" 2>/dev/null || true
    fi
done

# Clean journal logs older than 7 days
sudo journalctl --vacuum-time=7d 2>/dev/null || true

# Clean yum cache
sudo yum clean all 2>/dev/null || true
ENDSSH

echo ""

# Clean temp files
echo -e "${YELLOW}Cleaning temp files...${NC}"
ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
sudo rm -rf /tmp/* 2>/dev/null || true
sudo rm -rf /var/tmp/* 2>/dev/null || true
ENDSSH

echo ""

# Final disk usage
echo -e "${GREEN}Final disk usage:${NC}"
ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" "df -h /"

echo ""
echo -e "${GREEN}Cleanup complete!${NC}"
