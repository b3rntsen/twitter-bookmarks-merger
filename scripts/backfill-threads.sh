#!/bin/bash
# Script to backfill threads for bookmarks that are part of a thread
# Runs slowly with rate limit handling

set -e

SLEEP_INTERVAL=${SLEEP_INTERVAL:-300}  # 5 minutes default between runs
MAX_RUNS=${MAX_RUNS:-1000}  # Safety limit
BIRDMARKS_CACHE="birdmarks_cache"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PROJECT_DIR"

echo "🧵 Backfilling Threads for Existing Bookmarks"
echo "=============================================="
echo "   Sleep interval: ${SLEEP_INTERVAL}s ($(($SLEEP_INTERVAL / 60)) minutes)"
echo "   Cache: $BIRDMARKS_CACHE"
echo ""

# Count bookmarks with threads
thread_count=$(find "$BIRDMARKS_CACHE" -name "*.md" -type f -exec grep -l "thread_length: [2-9]" {} \; 2>/dev/null | wc -l | tr -d ' ')
total_count=$(find "$BIRDMARKS_CACHE" -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')

if [ "$total_count" -eq 0 ]; then
    echo "⚠️  No markdown files in cache"
    echo "   Run 'python3 scripts/convert-cached-bookmarks.py' first"
    exit 1
fi

echo "📊 Found $thread_count bookmarks with threads (out of $total_count total)"
echo ""

run_count=0
total_backfilled=0

while [ $run_count -lt $MAX_RUNS ]; do
    run_count=$((run_count + 1))
    echo "🔄 Run #${run_count}"
    echo "   Time: $(date '+%Y-%m-%d %H:%M:%S')"

    # Run birdmarks with --rebuild --backfill-replies
    echo "   Running: python3 tools/bookmark_merger.py fetch --until-synced --backfill-replies"

    if python3 tools/bookmark_merger.py fetch --until-synced --backfill-replies 2>&1; then
        echo "   ✅ Backfill run completed"
    else
        echo "   ⚠️  Backfill run had errors (may be rate limited)"
    fi

    # Check if we should continue
    # If no more threads to backfill, exit
    new_thread_count=$(find "$BIRDMARKS_CACHE" -name "*.md" -type f -exec grep -l "thread_length: [2-9]" {} \; 2>/dev/null | wc -l | tr -d ' ')

    if [ "$new_thread_count" -eq 0 ]; then
        echo ""
        echo "🎉 All threads backfilled!"
        echo "   Total runs: $run_count"
        exit 0
    fi

    echo "   📊 Threads remaining: $new_thread_count"
    echo ""
    echo "⏰ Waiting ${SLEEP_INTERVAL}s before next run..."
    echo "   Next run at: $(date -v +${SLEEP_INTERVAL}S '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -d "+${SLEEP_INTERVAL} seconds" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo 'in 5 minutes')"
    echo ""
    sleep $SLEEP_INTERVAL
done

echo ""
echo "⚠️  Reached maximum runs ($MAX_RUNS)"
echo "   Threads remaining: $(find "$BIRDMARKS_CACHE" -name "*.md" -type f -exec grep -l "thread_length: [2-9]" {} \; 2>/dev/null | wc -l | tr -d ' ')"
