#!/bin/bash
# Quick deployment script for Python code changes
# Syncs code and restarts containers without rebuilding Docker images
# Use this for rapid iteration when only Python code has changed

set -e

SSH_KEY="${SSH_KEY:-~/.ssh/twitter-bookmarks-key.pem}"
SERVER_USER="${SERVER_USER:-ec2-user}"
SERVER_HOST="${SERVER_HOST:-13.49.172.180}"
PROJECT_DIR="/home/${SERVER_USER}/twitter-bookmarks"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🚀 Quick deployment (code sync only, no rebuild)${NC}"
echo ""

# Check SSH key exists
if [ ! -f "$SSH_KEY" ]; then
  echo "❌ Error: SSH key not found at $SSH_KEY"
  exit 1
fi

# Sync Python code to server
echo -e "${YELLOW}📦 Syncing Python code...${NC}"
rsync -avz --progress \
  --include='web/***' \
  --include='tools/***' \
  --include='scripts/***' \
  --include='birdmarks/***' \
  --include='docker-compose.prod.yml' \
  --include='requirements.txt' \
  --exclude='*' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  "$LOCAL_PROJECT_DIR/" "${SERVER_USER}@${SERVER_HOST}:${PROJECT_DIR}/"

echo ""
echo -e "${YELLOW}🔄 Copying to containers and restarting...${NC}"

ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
cd /home/ec2-user/twitter-bookmarks

# Copy updated files to containers
echo "📋 Copying to web container..."
docker compose -f docker-compose.prod.yml cp web/ web:/app/web/

echo "📋 Copying to qcluster container..."
docker compose -f docker-compose.prod.yml cp web/ qcluster:/app/web/

# Copy birdmarks binary if it exists
if [ -f "birdmarks/birdmarks" ]; then
  echo "📋 Copying birdmarks binary..."
  docker compose -f docker-compose.prod.yml cp birdmarks/birdmarks web:/app/birdmarks/birdmarks
  docker compose -f docker-compose.prod.yml cp birdmarks/birdmarks qcluster:/app/birdmarks/birdmarks
fi

# Copy tools if they exist
if [ -d "tools" ]; then
  echo "📋 Copying tools..."
  docker compose -f docker-compose.prod.yml cp tools/ web:/app/tools/
  docker compose -f docker-compose.prod.yml cp tools/ qcluster:/app/tools/
fi

# Clean Python cache in containers
echo "🧹 Cleaning Python cache..."
docker compose -f docker-compose.prod.yml exec -T web find /app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
docker compose -f docker-compose.prod.yml exec -T web find /app -type f -name "*.pyc" -delete 2>/dev/null || true
docker compose -f docker-compose.prod.yml exec -T qcluster find /app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
docker compose -f docker-compose.prod.yml exec -T qcluster find /app -type f -name "*.pyc" -delete 2>/dev/null || true

# Restart containers
echo "🔄 Restarting containers..."
docker compose -f docker-compose.prod.yml restart web qcluster

# Wait for services
echo "⏳ Waiting for services..."
sleep 5

# Show status
echo ""
echo "📊 Service status:"
docker compose -f docker-compose.prod.yml ps

# Verify deployment
echo ""
echo "🔍 Verifying deployment..."
echo "Checking web container..."
docker compose -f docker-compose.prod.yml exec -T web ls -la /app/web/twitter/tasks.py >/dev/null 2>&1 && echo "  ✓ tasks.py" || echo "  ✗ tasks.py MISSING"
docker compose -f docker-compose.prod.yml exec -T web ls -la /app/web/twitter/models.py >/dev/null 2>&1 && echo "  ✓ models.py" || echo "  ✗ models.py MISSING"

echo "Checking qcluster container..."
docker compose -f docker-compose.prod.yml exec -T qcluster ls -la /app/web/twitter/tasks.py >/dev/null 2>&1 && echo "  ✓ tasks.py" || echo "  ✗ tasks.py MISSING"
docker compose -f docker-compose.prod.yml exec -T qcluster ls -la /app/web/twitter/models.py >/dev/null 2>&1 && echo "  ✓ models.py" || echo "  ✗ models.py MISSING"
ENDSSH

echo ""
echo -e "${GREEN}✅ Quick deployment complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Check logs: ssh -i $SSH_KEY ${SERVER_USER}@${SERVER_HOST} 'cd ${PROJECT_DIR} && docker compose -f docker-compose.prod.yml logs -f'"
echo "  2. Run E2E test: ./scripts/test-bookmark-sync.sh"
