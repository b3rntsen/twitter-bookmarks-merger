# Thread Backfill Script

## Purpose

Backfills complete thread content for bookmarks that are part of a Twitter thread. This is useful for:
- Bookmarks fetched before thread support was added
- Bookmarks where only the main tweet was saved initially
- Getting full context for threaded conversations

## How It Works

1. Scans all markdown files in `birdmarks_cache/` for bookmarks with `thread_length > 1`
2. Runs `birdmarks --rebuild --backfill-replies` to fetch missing thread content
3. Runs in a loop with configurable sleep intervals to respect rate limits
4. Automatically exits when all threads are backfilled

## Usage

```bash
# Run with default settings (5-minute sleep between runs)
./scripts/backfill-threads.sh

# Custom sleep interval (10 minutes)
SLEEP_INTERVAL=600 ./scripts/backfill-threads.sh

# Custom max runs (safety limit)
MAX_RUNS=100 ./scripts/backfill-threads.sh

# Combine settings
SLEEP_INTERVAL=900 MAX_RUNS=50 ./scripts/backfill-threads.sh
```

## Manual Usage

You can also run thread backfill manually:

```bash
# Backfill threads for existing bookmarks
python3 tools/bookmark_merger.py fetch --until-synced --backfill-replies

# Or run multiple times to handle rate limits
python3 tools/bookmark_merger.py fetch --until-synced --backfill-replies
# Wait for rate limit to reset...
python3 tools/bookmark_merger.py fetch --until-synced --backfill-replies
```

## What Happens

1. **First Run:** Birdmarks scans existing bookmarks and identifies those with incomplete threads
2. **Backfilling:** Fetches missing replies/thread content from Twitter
3. **Rate Limiting:** If rate limited, saves state and exits gracefully
4. **Resume:** Next run automatically resumes from where it left off
5. **Completion:** Stops when all threads have complete content

## Rate Limits

- Twitter has rate limits on API calls
- The script sleeps between runs to avoid hitting limits
- Default: 5 minutes (300 seconds)
- Recommended: 5-15 minutes depending on number of threads

## Progress Monitoring

The script shows:
- Number of bookmarks with threads
- Current run number
- Completion status
- Threads remaining to backfill

## After Completion

Once all threads are backfilled:

1. **Convert to JSON:**
   ```bash
   python3 scripts/convert-cached-bookmarks.py
   ```

2. **Merge into master:**
   ```bash
   python3 tools/bookmark_merger.py update
   ```

3. **Generate HTML:**
   ```bash
   python3 tools/bookmark_merger.py generate
   ```

## Notes

- Backfilling doesn't fetch new bookmarks, only adds thread content to existing ones
- The `birdmarks_cache/` directory must exist with markdown files
- If cache is empty, run `fetch --until-synced` first to populate it
- Thread content is added to the same markdown file, not creating duplicates

## Example Output

```
🧵 Backfilling Threads for Existing Bookmarks
==============================================
   Sleep interval: 300s (5 minutes)
   Cache: birdmarks_cache

📊 Found 127 bookmarks with threads (out of 1271 total)

🔄 Run #1
   Time: 2026-03-02 10:30:15
   Running: python3 tools/bookmark_merger.py fetch --until-synced --backfill-replies
   ✅ Backfill run completed
   📊 Threads remaining: 103

⏰ Waiting 300s before next run...
   Next run at: 2026-03-02 10:35:15
```

## Troubleshooting

**"No markdown files in cache"**
- Run `python3 tools/bookmark_merger.py fetch --until-synced` first

**Rate limit errors**
- Increase `SLEEP_INTERVAL` (e.g., 900 for 15 minutes)
- The script handles this automatically and will resume

**No threads found**
- Your bookmarks may not have threads
- Or threads were already backfilled in a previous run
