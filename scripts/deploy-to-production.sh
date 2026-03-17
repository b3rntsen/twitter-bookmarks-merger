#!/bin/bash
# Deployment script with automatic cleanup
# Deploys code to production and cleans up Docker resources

set -e

SSH_KEY="${SSH_KEY:-~/.ssh/twitter-bookmarks-key.pem}"
SERVER_USER="${SERVER_USER:-ec2-user}"
SERVER_HOST="${SERVER_HOST:-13.62.72.70}"
PROJECT_DIR="/home/${SERVER_USER}/twitter-bookmarks"

echo "🚀 Starting deployment to production..."

# Check disk usage before deployment
echo "📊 Checking disk usage before deployment..."
ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" \
  "df -h / | tail -1"

# Check if cleanup is needed (>70% disk usage)
DISK_USAGE=$(ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" \
  "df / | tail -1 | awk '{print \$5}' | sed 's/%//'")

if [ "$DISK_USAGE" -gt 70 ]; then
  echo "⚠️  Disk usage is ${DISK_USAGE}% - running cleanup first..."
  ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" \
    "cd ${PROJECT_DIR} && ./scripts/cleanup-docker.sh"
fi

# Deploy files using rsync (efficient, only uploads changed files)
echo "📦 Syncing code to server..."
rsync -avz --progress \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='._*' \
  --exclude='venv' \
  --exclude='.venv' \
  --exclude='node_modules' \
  --exclude='media' \
  --exclude='staticfiles' \
  --exclude='db.sqlite3' \
  --exclude='*.log' \
  --exclude='raw/' \
  --exclude='master/' \
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  "$(dirname "$(dirname "$0")")/" "${SERVER_USER}@${SERVER_HOST}:${PROJECT_DIR}/"

echo ""
echo "🔨 Rebuilding and restarting containers..."
ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
cd /home/ec2-user/twitter-bookmarks

# Stop containers
docker compose -f docker-compose.prod.yml down

# Clean Python cache
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Rebuild and start
docker compose -f docker-compose.prod.yml up -d --build

# Wait for services to be healthy
echo "⏳ Waiting for services to start..."
sleep 10

# Show service status
docker compose -f docker-compose.prod.yml ps
ENDSSH

# Run cleanup after deployment
echo "🧹 Running post-deployment cleanup..."
ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" \
  "cd ${PROJECT_DIR} && ./scripts/cleanup-docker.sh"

echo "✅ Deployment complete!"

