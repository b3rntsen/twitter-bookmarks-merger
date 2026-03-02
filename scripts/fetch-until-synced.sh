#!/bin/bash
# Script to run fetch --until-synced in a loop until gap is filled
# Handles rate limits by sleeping between runs

set -e

# Configuration
SLEEP_INTERVAL=${SLEEP_INTERVAL:-900}  # 15 minutes default (Twitter rate limit reset)
MAX_RUNS=${MAX_RUNS:-100}  # Safety limit to prevent infinite loops
STATE_FILE="birdmarks_cache/exporter-state.json"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PROJECT_DIR"

echo "🔄 Starting gap-free bookmark sync"
echo "=================================="
echo "   Sleep interval: ${SLEEP_INTERVAL}s ($(($SLEEP_INTERVAL / 60)) minutes)"
echo "   Max runs: $MAX_RUNS"
echo ""

run_count=0
total_new_bookmarks=0

while [ $run_count -lt $MAX_RUNS ]; do
    run_count=$((run_count + 1))
    echo "📥 Run #${run_count}"
    echo "   Time: $(date '+%Y-%m-%d %H:%M:%S')"

    # Check state file before run
    if [ -f "$STATE_FILE" ]; then
        # Check if already completed
        if grep -q '"allBookmarksProcessed"[[:space:]]*:[[:space:]]*true' "$STATE_FILE" 2>/dev/null; then
            echo "   ✅ All bookmarks already fetched (from previous run)"
            echo ""
            break
        fi

        # Check if has cursor (resuming from rate limit)
        if grep -q '"nextCursor"[[:space:]]*:[[:space:]]*"' "$STATE_FILE" 2>/dev/null; then
            echo "   📍 Resuming from saved cursor"
        fi
    fi

    # Run fetch command
    echo ""
    if python3 tools/bookmark_merger.py fetch --until-synced; then
        # Extract number of new bookmarks from output (if available)
        # This is a best-effort extraction

        # Check state file after run
        if [ -f "$STATE_FILE" ]; then
            if grep -q '"allBookmarksProcessed"[[:space:]]*:[[:space:]]*true' "$STATE_FILE" 2>/dev/null; then
                echo ""
                echo "🎉 Gap filled! All bookmarks synced."
                echo "   Total runs: $run_count"
                echo ""
                echo "Next step: Run 'python3 tools/bookmark_merger.py update' to merge into master"
                exit 0
            fi

            # Check if stopped early (found existing bookmarks)
            if grep -q '"stoppedAtExisting"[[:space:]]*:[[:space:]]*true' "$STATE_FILE" 2>/dev/null; then
                echo ""
                echo "🎉 Reached existing bookmarks! Gap filled."
                echo "   Total runs: $run_count"
                echo ""
                echo "Next step: Run 'python3 tools/bookmark_merger.py update' to merge into master"
                exit 0
            fi
        fi

        # Not done yet, continue after sleep
        echo ""
        echo "⏰ Waiting ${SLEEP_INTERVAL}s before next run (rate limit cooldown)..."
        echo "   Next run at: $(date -v +${SLEEP_INTERVAL}S '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -d "+${SLEEP_INTERVAL} seconds" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo 'in 15 minutes')"
        echo ""
        sleep $SLEEP_INTERVAL

    else
        echo ""
        echo "❌ Fetch failed on run #${run_count}"
        echo "   Check the error above"
        exit 1
    fi
done

echo ""
echo "⚠️  Reached maximum runs ($MAX_RUNS) without completing"
echo "   This might indicate an issue. Check the state file:"
echo "   cat $STATE_FILE"
