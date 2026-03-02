# Gap-Free Bookmark Sync Script

## Usage

```bash
# Run with default settings (15-minute sleep between runs)
./scripts/fetch-until-synced.sh

# Custom sleep interval (5 minutes)
SLEEP_INTERVAL=300 ./scripts/fetch-until-synced.sh

# Custom max runs (safety limit)
MAX_RUNS=50 ./scripts/fetch-until-synced.sh

# Combine settings
SLEEP_INTERVAL=600 MAX_RUNS=20 ./scripts/fetch-until-synced.sh
```

## How It Works

1. **Runs fetch --until-synced** in a loop
2. **Checks state file** after each run to detect completion
3. **Sleeps between runs** to respect Twitter rate limits (default 15 min)
4. **Automatically exits** when gap is filled
5. **Shows progress** including run count and next run time

## State Detection

The script checks for these completion signals:
- `allBookmarksProcessed: true` in state file
- `stoppedAtExisting: true` in state file (birdmarks found existing bookmarks)

## What Happens Next

After the script completes:
```bash
python3 tools/bookmark_merger.py update
```

This will merge all new bookmarks into master and categorize them.

## Monitoring

Each run shows:
- Run number and timestamp
- Whether resuming from cursor
- Progress (total exported so far)
- New bookmarks found
- Total bookmark count
- Next run time

## Safety Features

- Maximum runs limit (default 100) prevents infinite loops
- Exits immediately if already completed
- Shows clear error messages if fetch fails
- State file preserved between runs for resumption
