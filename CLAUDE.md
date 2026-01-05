# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Twitter/X bookmarks merger tool that processes exports from the "X Bookmarks Exporter" Chrome extension. It deduplicates bookmarks across multiple exports, consolidates downloaded media, generates browsable HTML pages, and uses Claude API for AI-powered categorization.

## Commands

```bash
# Activate virtual environment first
source .venv/bin/activate

# Processing commands
python3 tools/bookmark_merger.py merge        # Dedupe JSON → master/bookmarks.json
python3 tools/bookmark_merger.py consolidate  # Consolidate media → master/media/
python3 tools/bookmark_merger.py categorize   # AI categorization (needs ANTHROPIC_API_KEY)
python3 tools/bookmark_merger.py generate     # Generate HTML → master/html/
python3 tools/bookmark_merger.py export       # Export for NotebookLM → master/exports/
python3 tools/bookmark_merger.py all          # Run merge, consolidate, generate, export

# Incremental update (preferred for adding new exports)
python3 tools/bookmark_merger.py update       # Merge new, categorize NEW only, regenerate

# Cleanup commands
python3 tools/bookmark_merger.py clean        # Delete master/ to re-run (safe)
python3 tools/bookmark_merger.py cleanup-raw  # Delete raw/ (DESTRUCTIVE, separate step)
```

## Architecture

**Directory Structure:**
- `raw/json/` - Original JSON exports from XBookmarksExporter
- `raw/media/` - Original media export folders (named by export date)
- `master/` - Generated output (can be safely deleted and regenerated)

**Data Flow:**
1. Raw JSON exports deduplicated by Tweet ID (keeps most recent `Scraped At`)
2. Media files from all exports merged (skips `.crdownload` incomplete files)
3. AI categorization discovers taxonomy, assigns categories, generates summaries
4. HTML generation creates navigable pages with embedded local media

**Configuration:**
- `.env` - Stores `ANTHROPIC_API_KEY` for categorization
- Script auto-loads `.env` at startup

## Important Rules

- **Adding new exports**: Use `update` command - it only categorizes NEW bookmarks, preserving existing categorizations and saving API calls.
- **`clean` vs `cleanup-raw`**: These are intentionally separate commands. `clean` removes generated files and is safe to run anytime. `cleanup-raw` deletes original export data and should only be run after QA.
- **Re-running**: To regenerate all output, run `clean` then `all`. Never need to delete raw data to re-process.
- **Dependencies**: When adding new Python dependencies, add them to `requirements.txt`.
