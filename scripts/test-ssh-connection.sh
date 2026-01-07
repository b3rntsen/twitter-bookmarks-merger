#!/bin/bash
# Diagnostic script to test SSH connection to production

set -e

SSH_KEY="${SSH_KEY:-$HOME/.ssh/twitter-bookmarks-key.pem}"
SERVER_USER="${SERVER_USER:-ec2-user}"
SERVER_HOST="${SERVER_HOST:-13.62.72.70}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔍 Testing SSH Connection to Production${NC}"
echo "Server: ${SERVER_USER}@${SERVER_HOST}"
echo ""

# Check if key exists
if [ ! -f "$SSH_KEY" ]; then
    echo -e "${RED}❌ SSH key not found: $SSH_KEY${NC}"
    exit 1
fi

# Check key permissions
KEY_PERMS=$(stat -f "%OLp" "$SSH_KEY" 2>/dev/null || stat -c "%a" "$SSH_KEY" 2>/dev/null)
if [ "$KEY_PERMS" != "400" ] && [ "$KEY_PERMS" != "600" ]; then
    echo -e "${YELLOW}⚠️  SSH key permissions are $KEY_PERMS (should be 400 or 600)${NC}"
    echo "Fixing permissions..."
    chmod 400 "$SSH_KEY"
    echo -e "${GREEN}✅ Fixed permissions${NC}"
fi

# Test network connectivity
echo -e "${YELLOW}1. Testing network connectivity...${NC}"
if ping -c 2 -W 2 "$SERVER_HOST" &>/dev/null; then
    echo -e "${GREEN}✅ Ping successful${NC}"
else
    echo -e "${YELLOW}⚠️  Ping failed (this is normal - many servers block ICMP)${NC}"
fi

# Test port 22
echo -e "${YELLOW}2. Testing SSH port (22)...${NC}"
if nc -z -w 5 "$SERVER_HOST" 22 2>/dev/null || timeout 5 bash -c "echo > /dev/tcp/$SERVER_HOST/22" 2>/dev/null; then
    echo -e "${GREEN}✅ Port 22 is open${NC}"
else
    echo -e "${RED}❌ Port 22 is not accessible${NC}"
    echo "This could mean:"
    echo "  - Security group doesn't allow SSH from your IP"
    echo "  - Instance is stopped"
    echo "  - Network issue"
    exit 1
fi

# Test SSH connection
echo -e "${YELLOW}3. Testing SSH connection...${NC}"
if timeout 15 ssh -i "$SSH_KEY" \
    -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=no \
    -o BatchMode=yes \
    "${SERVER_USER}@${SERVER_HOST}" \
    "echo 'SSH connection successful'" 2>/dev/null; then
    echo -e "${GREEN}✅ SSH connection successful!${NC}"
    echo ""
    echo -e "${GREEN}Connection test:${NC}"
    ssh -i "$SSH_KEY" \
        -o ConnectTimeout=10 \
        -o StrictHostKeyChecking=no \
        "${SERVER_USER}@${SERVER_HOST}" \
        "echo 'Hostname:' \$(hostname) && echo 'Uptime:' \$(uptime -p) && echo 'User:' \$(whoami)"
else
    echo -e "${RED}❌ SSH connection failed${NC}"
    echo ""
    echo "Troubleshooting steps:"
    echo "1. Check if your IP has changed (security group might restrict access)"
    echo "2. Verify the instance is running in AWS Console"
    echo "3. Check security group allows SSH from your IP"
    echo "4. Try with verbose output:"
    echo "   ssh -v -i $SSH_KEY ${SERVER_USER}@${SERVER_HOST}"
    exit 1
fi

echo ""
echo -e "${GREEN}✅ All tests passed! SSH connection is working.${NC}"
