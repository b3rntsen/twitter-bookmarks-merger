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

# Deploy files (you can customize this section)
echo "📦 Deploying files..."
# Add your deployment commands here
# Example: scp files, git pull, etc.

# Rebuild Docker image
echo "🔨 Rebuilding Docker image..."
ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" \
  "cd ${PROJECT_DIR} && docker build -t twitter-bookmarks-web ."

# Restart services
echo "🔄 Restarting services..."
ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" \
  "cd ${PROJECT_DIR} && docker compose -f docker-compose.prod.yml up -d"

# Run cleanup after deployment
echo "🧹 Running post-deployment cleanup..."
ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" \
  "cd ${PROJECT_DIR} && ./scripts/cleanup-docker.sh"

echo "✅ Deployment complete!"

