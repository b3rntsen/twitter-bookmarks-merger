# Twitter Bookmarks Merger

Merge multiple X/Twitter bookmark exports, deduplicate, generate browsable HTML pages, and use AI to categorize your bookmarks.

Works with exports from the [X Bookmarks Exporter](https://chromewebstore.google.com/detail/x-bookmarks-exporter-expo/abgjpimjfnggkhnoehjndcociampccnm) Chrome extension.

## Setup

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Add your Anthropic API key (for AI categorization)
echo "ANTHROPIC_API_KEY=your-key-here" > .env
```

## Quick Start

**Process all bookmarks:**
```bash
python3 tools/bookmark_merger.py all
```

**View the results:**
```bash
open master/html/index.html
```

## Commands

| Command | Description |
|---------|-------------|
| `merge` | Deduplicate JSON files → `master/bookmarks.json` |
| `consolidate` | Consolidate media files → `master/media/` |
| `categorize` | AI-powered categorization (requires API key) |
| `generate` | Generate HTML pages → `master/html/` |
| `export` | Export for NotebookLM → `master/exports/` |
| `all` | Run merge, consolidate, generate, export |
| `clean` | Delete generated files to re-run processing |
| `cleanup-raw` | Delete raw exports (DESTRUCTIVE - requires confirmation) |

## Workflow

### First time setup

1. Export your bookmarks using the Chrome extension
2. Place JSON files in `raw/json/`
3. Place media export folders in `raw/media/`
4. Run `python3 tools/bookmark_merger.py all`

### Adding new exports

1. Add new JSON files to `raw/json/`
2. Add new media folders to `raw/media/`
3. Clean and re-run:
   ```bash
   python3 tools/bookmark_merger.py clean
   python3 tools/bookmark_merger.py all
   ```

### With AI categorization

```bash
python3 tools/bookmark_merger.py clean
python3 tools/bookmark_merger.py merge
python3 tools/bookmark_merger.py consolidate
python3 tools/bookmark_merger.py categorize
python3 tools/bookmark_merger.py generate
python3 tools/bookmark_merger.py export
```

### After QA - delete raw data

Once you've verified `master/` contains all your data:
```bash
python3 tools/bookmark_merger.py cleanup-raw
```
This requires typing `DELETE` to confirm.

## Directory Structure

```
├── raw/                    # Original exports (input)
│   ├── json/               # JSON export files
│   └── media/              # Media export folders
├── master/                 # Processed output
│   ├── bookmarks.json      # Deduplicated bookmarks
│   ├── categories.json     # AI categories (after categorize)
│   ├── media/              # Consolidated media files
│   ├── html/               # Browsable HTML pages
│   └── exports/            # NotebookLM text exports
├── tools/
│   └── bookmark_merger.py  # Main CLI tool
├── .env                    # API key (not committed)
└── requirements.txt        # Python dependencies
```

## Features

- **Deduplication**: Merges multiple exports, keeps most recent version of each tweet
- **Media consolidation**: Combines media from all exports, handles partial downloads
- **AI categorization**: Claude discovers categories and generates summaries per time period
- **HTML generation**: Browsable pages with search, dark mode, embedded media
- **Timeline navigation**: Browse by year, month, or category
- **NotebookLM export**: Plain text format for uploading to Google NotebookLM
