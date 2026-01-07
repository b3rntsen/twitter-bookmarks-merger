#!/bin/bash
# Script to add Anthropic API key to production .env file

set -e

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

echo -e "${BLUE}🔑 Adding Anthropic API Key to Production${NC}"
echo ""

# Check if key is provided as argument
if [ -z "$1" ]; then
    echo -e "${YELLOW}Usage: $0 <your-anthropic-api-key>${NC}"
    echo ""
    echo "Or set it interactively:"
    read -sp "Enter your Anthropic API key: " API_KEY
    echo ""
    if [ -z "$API_KEY" ]; then
        echo -e "${RED}❌ No API key provided${NC}"
        exit 1
    fi
else
    API_KEY="$1"
fi

# Validate key format (should start with sk-ant-)
if [[ ! "$API_KEY" =~ ^sk-ant- ]]; then
    echo -e "${YELLOW}⚠️  Warning: API key doesn't start with 'sk-ant-'${NC}"
    echo "Are you sure this is a valid Anthropic API key?"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo -e "${YELLOW}Adding API key to production .env file...${NC}"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" << ENDSSH
    set -e
    cd ${PROJECT_DIR_REMOTE}
    
    # Backup .env file
    if [ -f .env ]; then
        cp .env .env.backup.\$(date +%Y%m%d_%H%M%S)
        echo "✅ Backed up .env file"
    fi
    
    # Remove existing ANTHROPIC_API_KEY line if present
    if grep -q '^ANTHROPIC_API_KEY=' .env 2>/dev/null; then
        sed -i '/^ANTHROPIC_API_KEY=/d' .env
        echo "✅ Removed existing ANTHROPIC_API_KEY"
    fi
    
    # Add new API key
    echo "ANTHROPIC_API_KEY=${API_KEY}" >> .env
    echo "✅ Added ANTHROPIC_API_KEY to .env"
    
    # Also add model if not present
    if ! grep -q '^ANTHROPIC_MODEL=' .env 2>/dev/null; then
        echo "ANTHROPIC_MODEL=claude-sonnet-4-20250514" >> .env
        echo "✅ Added ANTHROPIC_MODEL to .env"
    fi
    
    # Verify
    if grep -q '^ANTHROPIC_API_KEY=' .env; then
        echo ""
        echo "✅ API key added successfully!"
        echo "   Key length: \$(grep '^ANTHROPIC_API_KEY=' .env | cut -d'=' -f2 | wc -c) characters"
    else
        echo "❌ Failed to add API key"
        exit 1
    fi
ENDSSH

echo ""
echo -e "${GREEN}✅ API key added to production!${NC}"
echo ""
echo -e "${YELLOW}⚠️  Note: You may need to restart the containers for the change to take effect:${NC}"
echo "   ssh -i $SSH_KEY ${SERVER_USER}@${SERVER_HOST}"
echo "   cd ${PROJECT_DIR_REMOTE}"
echo "   docker compose -f docker-compose.prod.yml restart web"
echo ""
echo "Or use the release script which will restart automatically:"
echo "   ./scripts/release.sh"
