#!/bin/bash
# Deploy twitter_bookmarks static HTML and media to twitter.dethele.com
#
# Usage: ./scripts/deploy-bookmarks.sh [--html-only] [--media-only]
#
# Prerequisites:
# 1. SSH access to the EC2 server
# 2. Run 'publish-server' command first to generate HTML

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
SERVER_USER="${SERVER_USER:-ec2-user}"
SERVER_HOST="${SERVER_HOST:-twitter.dethele.com}"
SERVER="${SERVER_USER}@${SERVER_HOST}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/twitter-bookmarks-key.pem}"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no"

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVER_HTML="${PROJECT_DIR}/server/html"
MASTER_MEDIA="${PROJECT_DIR}/master/media"
REMOTE_DIR="/home/${SERVER_USER}/twitter-bookmarks"

# Parse arguments
HTML_ONLY=false
MEDIA_ONLY=false

for arg in "$@"; do
    case $arg in
        --html-only)
            HTML_ONLY=true
            ;;
        --media-only)
            MEDIA_ONLY=true
            ;;
        -h|--help)
            echo "Usage: $0 [--html-only] [--media-only]"
            echo ""
            echo "Options:"
            echo "  --html-only   Only sync HTML files"
            echo "  --media-only  Only sync media files"
            exit 0
            ;;
    esac
done

echo -e "${GREEN}=== Deploying to ${SERVER_HOST} ===${NC}"
echo ""

# Generate server HTML if needed
if [ ! -d "$SERVER_HTML" ]; then
    echo -e "${YELLOW}Server HTML not found. Generating...${NC}"
    cd "$PROJECT_DIR"
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    fi
    python3 tools/bookmark_merger.py publish-server
    echo ""
fi

# Create remote directories if they don't exist
echo "Ensuring remote directories exist..."
ssh $SSH_OPTS "$SERVER" "mkdir -p ${REMOTE_DIR}/bookmarks-html ${REMOTE_DIR}/bookmarks-media"

# Deploy HTML
if [ "$MEDIA_ONLY" = false ]; then
    echo -e "${YELLOW}Syncing HTML...${NC}"
    rsync -avz --delete \
        -e "ssh $SSH_OPTS" \
        --exclude '.DS_Store' \
        "$SERVER_HTML/" \
        "${SERVER}:${REMOTE_DIR}/bookmarks-html/"
    echo ""
fi

# Deploy media
if [ "$HTML_ONLY" = false ]; then
    echo -e "${YELLOW}Syncing media (this may take a while for first sync)...${NC}"
    rsync -avz --progress \
        -e "ssh $SSH_OPTS" \
        --exclude '.DS_Store' \
        "$MASTER_MEDIA/" \
        "${SERVER}:${REMOTE_DIR}/bookmarks-media/"
    echo ""
fi

echo -e "${GREEN}✓ Deployment complete!${NC}"
echo ""
echo "View at: https://${SERVER_HOST}/"
