#!/bin/bash
# Docker cleanup script for production server
# Removes unused containers, images, build cache, and volumes

set -e

echo "🧹 Starting Docker cleanup..."

# Show current disk usage
echo "📊 Current disk usage:"
df -h / | tail -1
echo ""
echo "📦 Current Docker usage:"
docker system df
echo ""

# Remove stopped containers
echo "🗑️  Removing stopped containers..."
docker container prune -f

# Remove unused images (keep last 2 versions)
echo "🗑️  Removing unused images (keeping last 2)..."
docker images --format "{{.Repository}}:{{.Tag}}" | grep twitter-bookmarks | tail -n +3 | xargs -r docker rmi -f 2>/dev/null || true

# Remove dangling images
docker image prune -f

# Remove build cache (keeps recent builds)
echo "🗑️  Removing old build cache..."
docker builder prune -f --filter "until=24h"

# Remove unused volumes (be careful - this removes volumes not used by any container)
echo "🗑️  Removing unused volumes..."
docker volume prune -f

# Final disk usage
echo ""
echo "✅ Cleanup complete!"
echo "📊 Final disk usage:"
df -h / | tail -1
echo ""
echo "📦 Final Docker usage:"
docker system df

