#!/bin/bash
# Script to cleanup orphaned browser processes (headless Chrome/Chromium)
# Run this if you notice high load from browser processes

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🧹 Cleaning up orphaned browser processes${NC}"
echo ""

# Count processes before cleanup
CHROME_COUNT=$(ps aux | grep -E '[c]hrome.*headless|[c]hromium.*headless|headless_shell' | wc -l | tr -d ' ')
PLAYWRIGHT_COUNT=$(ps aux | grep -E '[p]laywright|pwsh' | wc -l | tr -d ' ')

echo -e "${YELLOW}Found processes:${NC}"
echo "  Chrome/Chromium headless: $CHROME_COUNT"
echo "  Playwright: $PLAYWRIGHT_COUNT"
echo ""

if [ "$CHROME_COUNT" -eq 0 ] && [ "$PLAYWRIGHT_COUNT" -eq 0 ]; then
    echo -e "${GREEN}✅ No orphaned browser processes found${NC}"
    exit 0
fi

# Ask for confirmation
read -p "Kill these processes? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# Kill Chrome/Chromium headless processes
echo -e "${YELLOW}Killing Chrome/Chromium headless processes...${NC}"
pkill -f 'chrome.*headless' 2>/dev/null || true
pkill -f 'chromium.*headless' 2>/dev/null || true
pkill -f 'headless_shell' 2>/dev/null || true

# Kill Playwright processes
echo -e "${YELLOW}Killing Playwright processes...${NC}"
pkill -f 'playwright' 2>/dev/null || true

# Wait a moment
sleep 2

# Count after cleanup
CHROME_AFTER=$(ps aux | grep -E '[c]hrome.*headless|[c]hromium.*headless|headless_shell' | wc -l | tr -d ' ')
PLAYWRIGHT_AFTER=$(ps aux | grep -E '[p]laywright|pwsh' | wc -l | tr -d ' ')

echo ""
if [ "$CHROME_AFTER" -eq 0 ] && [ "$PLAYWRIGHT_AFTER" -eq 0 ]; then
    echo -e "${GREEN}✅ All browser processes cleaned up${NC}"
else
    echo -e "${YELLOW}⚠️  Some processes may still be running:${NC}"
    echo "  Chrome/Chromium: $CHROME_AFTER"
    echo "  Playwright: $PLAYWRIGHT_AFTER"
    echo ""
    echo "You may need to kill them manually:"
    echo "  ps aux | grep -E 'chrome|chromium|playwright'"
    echo "  kill -9 <PID>"
fi
