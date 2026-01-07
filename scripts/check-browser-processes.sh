#!/bin/bash
# Script to check for orphaned browser processes on production server
# Run this to monitor browser process leaks

echo "=== Browser Process Check ==="
echo ""

# Count processes
CHROME_COUNT=$(ps aux | grep -E '[c]hrome.*headless|[c]hromium.*headless|headless_shell' | wc -l | tr -d ' ')
PLAYWRIGHT_COUNT=$(ps aux | grep -E '[p]laywright' | wc -l | tr -d ' ')

echo "Current processes:"
echo "  Chrome/Chromium headless: $CHROME_COUNT"
echo "  Playwright: $PLAYWRIGHT_COUNT"
echo ""

if [ "$CHROME_COUNT" -gt 0 ] || [ "$PLAYWRIGHT_COUNT" -gt 0 ]; then
    echo "⚠️  Found browser processes. Details:"
    echo ""
    ps aux | grep -E '[c]hrome.*headless|[c]hromium.*headless|headless_shell|[p]laywright' | head -20
    echo ""
    echo "To kill these processes, run:"
    echo "  ./scripts/cleanup-browsers.sh"
else
    echo "✅ No browser processes found"
fi

echo ""
echo "System load:"
uptime

echo ""
echo "Memory usage:"
free -h 2>/dev/null || vm_stat | head -10
