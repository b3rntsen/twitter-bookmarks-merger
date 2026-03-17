# Architecture Analysis: Twitter Bookmarks

## Purpose

A personal system for collecting, preserving, categorizing, and browsing Twitter/X bookmarks. Two independent subsystems serve complementary roles:

1. **CLI Tools** (`tools/`) - Batch processing: import exports, AI-categorize, generate a static browsable HTML site
2. **Django App** (`web/`) - Live system: automated bookmark fetching via scheduled jobs, web UI for status/management

Both produce browsable bookmark collections, but they share almost no code and have separate data stores.

---

## System Diagram

```
                        TWITTER/X
                            |
              +-------------+-------------+
              |                           |
     Chrome Extension               birdmarks binary
     (manual export)              (API via cookies)
              |                           |
              v                           v
         raw/json/*.json          birdmarks_cache/*.md
              |                     /           \
              |                    /             \
              v                   v               v
    +------------------+   tools/              web/twitter/
    | CLI Pipeline     |   birdmarks_bridge    tasks.py
    | (bookmark_merger)|        |                  |
    |                  |        v                   v
    | merge/update ----+-> raw/json/           SQLite DB
    | categorize (AI)  |   birdmarks-*.json    (Tweet model)
    | generate HTML    |        |                  |
    | stories (AI)     |        |                  v
    | authors (AI)     |        |           Django Web UI
    +------------------+        |           /new-gen/*
           |                    |
           v                    |
     master/                    |
     +-- bookmarks.json         |
     +-- categories.json        |
     +-- stories.json           |
     +-- authors.json           |
     +-- html/  -----+         |
     +-- media/       |         |
                      |         |
         +------------+---------+--------+
         |            |                  |
         v            v                  v
    Local Browse   GitHub Pages     EC2 Server
    (file://)     (dethele.com/    (twitter.dethele.com)
                   twitter/)       nginx + Docker
                   CDN media       local media + Django
```

---

## The Two Systems

### System A: CLI Pipeline (`tools/bookmark_merger.py` - 5,751 lines)

**Data store:** JSON files in `master/`
**Input sources:** Chrome extension exports (`raw/json/`), birdmarks fetch
**Output:** Static HTML site with search, categories, stories, authors

#### Commands and Data Flow

```
INPUT COMMANDS (get data in):
  fetch          birdmarks binary -> markdown -> raw/json/birdmarks-*.json
  (manual)       Chrome extension export -> raw/json/XBookmarks*.json

PROCESSING COMMANDS (transform data):
  merge          raw/json/* -> master/bookmarks.json           [DANGEROUS: ignores existing]
  update         master/bookmarks.json + raw/json/* -> merged  [SAFE: preserves existing]
  consolidate    raw/media/* -> master/media/{tweet_id}/
  categorize     master/bookmarks.json -> master/categories.json (AI, ALL tweets)
  stories        master/bookmarks.json + categories -> master/stories.json (AI)
  authors        master/bookmarks.json -> master/authors.json (AI)
  fetch-quotes   Twitter oEmbed API -> master/quoted_tweets.json
  thumbnails     master/media/*.mp4 -> master/media/thumb_*.jpg (ffmpeg)

OUTPUT COMMANDS (publish):
  generate       master/* -> master/html/        (relative media paths)
  publish-server master/* -> server/html/        (absolute /media/bookmarks/ paths)
  publish        master/* -> GitHub Pages        (Twitter CDN URLs, no local media)
  sync           update + generate + deploy to EC2

UTILITY:
  clean          delete master/ (safe, regenerable)
  cleanup-raw    delete raw/ (destructive, with verification)
  all            merge + consolidate + generate + export
```

#### Key Design Decisions
- Deduplication by Tweet ID, keeps newest `Scraped At` timestamp
- `update`/`sync` are safe (merge existing + new); `merge` is dangerous (raw only)
- AI categorization: 3-phase (discover taxonomy, assign categories, generate summaries)
- HTML: infinite scroll with chunked JSON (100 tweets/chunk), client-side search
- Three rendering modes: local (relative paths), server (absolute paths), CDN (Twitter URLs)

---

### System B: Django App (`web/`)

**Data store:** SQLite database
**Input source:** birdmarks binary (via scheduled jobs)
**Output:** Web UI at `/new-gen/`

#### Django Apps

| App | Purpose | Models |
|-----|---------|--------|
| `twitter` | Core: Twitter accounts, tweets, sync | TwitterProfile, Tweet, TweetMedia, TweetThread, TweetReply, BookmarkSyncSchedule, BookmarkSyncJob |
| `bookmarks_app` | Curated feed (AI categorized bookmarks) | CuratedFeed, TweetCategory, CategorizedTweet |
| `lists_app` | Twitter list monitoring | TwitterList, ListTweet, Event, EventTweet |
| `processing_app` | Job scheduling & orchestration | ContentProcessingJob, ProcessingSchedule, DailyContentSnapshot |
| `accounts` | User auth, invitations | UserProfile, Invitation |

#### URL Routes

```
/accounts/          Google OAuth (allauth)
/accounts/admin/    User management panel
/new-gen/admin/     Django admin
/new-gen/           Bookmarks app (curated feed views)
/new-gen/twitter/   Connect/disconnect Twitter, sync status
/new-gen/lists/     Twitter list views
/new-gen/processing/ Processing status dashboard
```

#### Automated Sync Flow

```
User connects Twitter -> TwitterProfile created (encrypted cookies)
    -> BookmarkSyncSchedule created (default: 60min interval)
    -> schedule_next_bookmark_sync()
    -> Django-Q schedule() one-time job
    -> [at scheduled time] execute_bookmark_sync()
        -> runs birdmarks binary with cookies from DB
        -> outputs markdown to /tmp/
        -> import_markdown_bookmarks() parses -> Tweet records
        -> schedule_next_bookmark_sync() (loop)
    -> auto-disable after 5 consecutive failures
```

#### Three Content Processors (processing_app)

1. **BookmarkProcessor** - Fetches bookmarks via birdmarks
2. **CuratedFeedProcessor** - AI-categorizes recent timeline tweets
3. **ListProcessor** - Fetches tweets from subscribed Twitter lists

Each creates `ContentProcessingJob` records for tracking.

---

## Overlap and Inconsistencies

### 1. Two Separate Data Stores, Same Data

| Aspect | CLI (tools/) | Django (web/) |
|--------|-------------|---------------|
| Storage | `master/bookmarks.json` (flat file) | SQLite `twitter_tweet` table |
| Format | XBookmarksExporter JSON | Django ORM / Tweet model |
| Categories | `master/categories.json` | `bookmarks_app_tweetcategory` table |
| Media | `master/media/{tweet_id}/` | `media/tweets/{tweet_id}/` |
| Sync bridge | `import_master_json` / `export_to_master_json` mgmt commands | Manual, rarely used |

**Problem:** Data drifts. CLI has ~all bookmarks (from exports). Django has only what was fetched via automated sync. No automatic bidirectional sync.

### 2. Two Bookmark Fetching Mechanisms

Both use the same `birdmarks` binary but differently:

| Aspect | CLI fetch | Django sync |
|--------|-----------|-------------|
| Invoked by | `tools/birdmarks_bridge.py` | `web/twitter/tasks.py` |
| Cookie source | `~/.openclaw/secrets/twitter-cookies.json` | `TwitterProfile.encrypted_credentials` (DB) |
| Output | Markdown -> JSON in `raw/json/` | Markdown -> Tweet DB records |
| Media | Copies to `master/media/` | Copies to `media/tweets/` |
| State | `birdmarks_cache/exporter-state.json` | `BookmarkSyncJob` + `BookmarkSyncSchedule` |

**Problem:** Same operation, two implementations, two sets of cookies, two output locations.

### 3. Two Categorization Systems

| Aspect | CLI categorize | Django CuratedFeed |
|--------|---------------|-------------------|
| Scope | ALL bookmarks | Recent timeline tweets only |
| Storage | `master/categories.json` | `TweetCategory` + `CategorizedTweet` DB tables |
| Taxonomy | Discovered dynamically per run | Per-feed, ephemeral |
| Persistence | Survives across runs | Per CuratedFeed instance |

### 4. Two HTML Rendering Pipelines

| Aspect | CLI generate | Django templates |
|--------|-------------|-----------------|
| Tech | Python string templates in bookmark_merger.py | Django/Jinja2 templates |
| Output | Static HTML with JS infinite scroll | Server-rendered HTML |
| Features | Search, categories, stories, authors, timeline | Tweet cards, sync status |
| Location | `master/html/` or `server/html/` | Served by Django views |

### 5. Duplicate Tweet Model Concepts

The CLI's bookmark JSON structure and Django's Tweet model represent the same entity but with different field names, different date formats, and different media handling.

### 6. Scheduling Overlap

- `BookmarkSyncSchedule` (twitter app) - schedules bookmark fetching
- `ProcessingSchedule` (processing_app) - schedules daily content processing
- Both use Django-Q but with different patterns

---

## Feature Inventory

### Working Features (CLI)
- Import from Chrome extension exports
- Fetch via birdmarks binary
- Deduplicate bookmarks
- AI categorization (taxonomy discovery + assignment + summaries)
- AI stories (narrative timelines per category/year)
- AI author profiles
- Static HTML generation (3 modes: local, server, CDN)
- Infinite scroll, client-side search, category filtering
- Quoted tweet embeds
- Video thumbnail generation
- Safe incremental updates (update/sync)
- Data loss protection (backups, merge verification)
- Deploy to EC2 or GitHub Pages

### Working Features (Django)
- Google OAuth login
- Connect Twitter account (encrypted cookie storage)
- Automated bookmark sync (scheduled via Django-Q)
- Sync health monitoring + auto-disable on failures
- Tweet storage with media
- Admin panel for user/sync management

### Partially Working / Unused (Django)
- Curated feed (bookmarks_app) - has models + processors, unclear if actively used
- Twitter lists (lists_app) - has models + views, unclear if actively used
- Processing app orchestration - designed for 3 content types, mainly used for bookmarks
- Browser-based scraping (TwitterScraper, TwikitScraper) - replaced by birdmarks
- REST framework installed but no API endpoints defined
- Thread backfilling (management commands exist)

---

## Deployment Architecture

```
EC2 (13.62.72.70) - Docker Compose
+-----------------------------------------------------+
| nginx:443                                            |
|   / ---------> bookmarks-html/ (static, from CLI)   |
|   /media/bookmarks/ -> bookmarks-media/ (from CLI)  |
|   /new-gen/ -> web:8000 (Django)                     |
|   /accounts/ -> web:8000 (OAuth)                     |
|   All routes require Google OAuth (except /accounts) |
+-----------------------------------------------------+
| web:8000          | qcluster         | redis:6379   |
| Django app        | Django-Q worker  | Job queue    |
| SQLite DB         | Runs birdmarks   |              |
+-----------------------------------------------------+
| certbot: SSL auto-renewal every 12h                  |
+-----------------------------------------------------+
```

Two content systems coexist on the same server:
- **Static site** (root `/`): Generated by CLI tools, deployed via rsync
- **Django app** (`/new-gen/`): Live application with automated sync

---

## Rules for Feature Implementation

### Before Starting Any Feature

1. **Identify which system it belongs to.** CLI tools and Django are separate. Don't add Django features that duplicate CLI functionality or vice versa.
2. **Check for existing implementations.** The codebase has accumulated duplicate solutions. Search before building.
3. **Respect the data flow direction.** CLI reads JSON files. Django reads the database. Don't create cross-dependencies without explicit bridge commands.

### Implementation Rules

1. **One source of truth per data type.** If bookmarks live in `master/bookmarks.json` for the CLI, don't also maintain a parallel copy in a Django model that drifts. Use bridge commands (import/export) if needed.
2. **Don't add features to the wrong system.** Interactive, user-facing, real-time features belong in Django. Batch processing, AI analysis, and static site generation belong in CLI tools.
3. **Don't create new rendering modes.** There are already 3 HTML generation modes (local, server, CDN) + Django templates. Unify before adding more.
4. **Keep AI features in the CLI.** The CLI has the AI categorization, stories, and authors infrastructure. Don't replicate this in Django unless migrating fully.
5. **Test the deployment path, not just the code.** Changes must work inside Docker containers. Verify files exist in containers, not just locally.

### Bug Fix Rules

1. **Trace the full data flow.** A bug in the HTML might originate in categorization, which originates in merge. Follow the chain.
2. **Check both systems.** A bug in bookmark display could be in CLI-generated HTML OR Django templates depending on which URL the user is on.
3. **Verify on the server.** Local testing misses deployment issues (missing files, wrong paths, container state).

### Test Case Rules

1. **CLI tools:** Test with a small set of known bookmarks in `raw/json/`. Verify output JSON structure and HTML generation.
2. **Django app:** Use management commands for E2E tests. `check_bookmark_sync_health` for sync system health.
3. **Deployment:** Run `verify-deployment.sh` before deploying. Run `test-bookmark-sync.sh` after deploying.
4. **AI features:** Use `--dry-run` where available. Check API costs before full runs.

---

## Known Technical Debt

1. **5,751-line monolith** (`bookmark_merger.py`) - All CLI commands, HTML templates, AI logic in one file
2. **Deprecated code in Django** - Old browser scrapers (TwitterScraper, TwikitScraper), threading-based sync, unused REST framework
3. **No shared library** - Tweet parsing, date formatting, media handling reimplemented in both systems
4. **SQLite in production** - Works for single-user, but limits concurrent access (qcluster + web)
5. **Hardcoded paths** - Binary paths, cookie file locations, media directories scattered through code
6. **No automated tests for CLI** - Only Django has test files (and unclear how many pass)
7. **Template strings in Python** - HTML templates embedded as string constants in bookmark_merger.py
