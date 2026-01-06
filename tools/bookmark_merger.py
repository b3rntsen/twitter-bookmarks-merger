#!/usr/bin/env python3
"""
Twitter Bookmarks Merger Tool

Merge multiple X/Twitter bookmark exports, deduplicate, generate HTML views,
categorize with AI, and export for NotebookLM.

Usage:
    python bookmark_merger.py merge       # Deduplicate JSON files
    python bookmark_merger.py consolidate # Consolidate media files
    python bookmark_merger.py categorize  # AI categorization (all bookmarks)
    python bookmark_merger.py generate    # Generate HTML pages
    python bookmark_merger.py export      # Export for NotebookLM
    python bookmark_merger.py stories     # Generate AI stories for categories
    python bookmark_merger.py update      # Incremental: merge new, categorize new only
    python bookmark_merger.py all         # Run merge, consolidate, generate, export
    python bookmark_merger.py publish     # Publish to dethele.com/twitter (CDN media)
    python bookmark_merger.py unpublish   # Remove from dethele.com (DESTRUCTIVE)
    python bookmark_merger.py clean       # Delete generated files to re-run
    python bookmark_merger.py cleanup-raw # Delete raw exports (DESTRUCTIVE)
"""

import argparse
import json
import markdown
import os
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# Base paths
BASE_DIR = Path(__file__).parent.parent

# Load .env file if it exists
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
RAW_DIR = BASE_DIR / "raw"
RAW_JSON_DIR = RAW_DIR / "json"
RAW_MEDIA_DIR = RAW_DIR / "media"
MASTER_DIR = BASE_DIR / "master"
MASTER_JSON = MASTER_DIR / "bookmarks.json"
MASTER_CATEGORIES = MASTER_DIR / "categories.json"
MASTER_STORIES = MASTER_DIR / "stories.json"
MASTER_MEDIA_DIR = MASTER_DIR / "media"
MASTER_HTML_DIR = MASTER_DIR / "html"
MASTER_EXPORTS_DIR = MASTER_DIR / "exports"


def load_all_json_files() -> list[dict]:
    """Load all JSON bookmark files from raw/json/"""
    all_bookmarks = []
    json_files = list(RAW_JSON_DIR.glob("*.json"))

    if not json_files:
        print(f"No JSON files found in {RAW_JSON_DIR}")
        return []

    for json_file in json_files:
        print(f"Loading {json_file.name}...")
        with open(json_file, "r", encoding="utf-8") as f:
            bookmarks = json.load(f)
            print(f"  Found {len(bookmarks)} bookmarks")
            all_bookmarks.extend(bookmarks)

    return all_bookmarks


def deduplicate_bookmarks(bookmarks: list[dict]) -> list[dict]:
    """Deduplicate bookmarks by Tweet ID, keeping most recent scraped_at"""
    by_id: dict[str, dict] = {}

    for bookmark in bookmarks:
        tweet_id = bookmark.get("Tweet Id")
        if not tweet_id:
            continue

        if tweet_id not in by_id:
            by_id[tweet_id] = bookmark
        else:
            # Keep the one with more recent scraped_at
            existing_scraped = by_id[tweet_id].get("Scraped At", "")
            new_scraped = bookmark.get("Scraped At", "")
            if new_scraped > existing_scraped:
                by_id[tweet_id] = bookmark

    return list(by_id.values())


def cmd_merge(args: argparse.Namespace) -> None:
    """Merge and deduplicate JSON files"""
    print("=== Merging JSON files ===")

    all_bookmarks = load_all_json_files()
    if not all_bookmarks:
        return

    print(f"\nTotal bookmarks loaded: {len(all_bookmarks)}")

    deduped = deduplicate_bookmarks(all_bookmarks)
    print(f"After deduplication: {len(deduped)}")
    print(f"Duplicates removed: {len(all_bookmarks) - len(deduped)}")

    # Sort by created date (newest first) - parse actual date, not string sort
    from datetime import timezone
    deduped.sort(key=lambda x: parse_tweet_date(x.get("Created At", "")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    # Ensure master directory exists
    MASTER_DIR.mkdir(parents=True, exist_ok=True)

    # Write merged JSON
    with open(MASTER_JSON, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)

    print(f"\nWritten to {MASTER_JSON}")


def cmd_consolidate(args: argparse.Namespace) -> None:
    """Consolidate media files from all exports"""
    print("=== Consolidating media files ===")

    if not RAW_MEDIA_DIR.exists():
        print(f"Raw media directory not found: {RAW_MEDIA_DIR}")
        return

    export_dirs = [d for d in RAW_MEDIA_DIR.iterdir() if d.is_dir()]
    print(f"Found {len(export_dirs)} export directories")

    # Collect all media files by tweet ID
    media_by_tweet: dict[str, dict[str, Path]] = defaultdict(dict)

    for export_dir in export_dirs:
        print(f"Scanning {export_dir.name}...")
        for tweet_dir in export_dir.iterdir():
            if not tweet_dir.is_dir() or not tweet_dir.name.isdigit():
                continue

            tweet_id = tweet_dir.name
            for media_file in tweet_dir.iterdir():
                if media_file.is_file() and not media_file.suffix == ".crdownload":
                    # Use filename as key to avoid duplicates
                    media_by_tweet[tweet_id][media_file.name] = media_file

    print(f"\nFound media for {len(media_by_tweet)} tweets")

    # Copy to master directory
    total_files = 0
    for tweet_id, files in media_by_tweet.items():
        dest_dir = MASTER_MEDIA_DIR / tweet_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        for filename, source_path in files.items():
            dest_path = dest_dir / filename
            if not dest_path.exists():
                shutil.copy2(source_path, dest_path)
                total_files += 1

    print(f"Copied {total_files} media files to {MASTER_MEDIA_DIR}")


def parse_tweet_date(date_str: str) -> datetime | None:
    """Parse Twitter date format: 'Sun Jan 04 14:36:22 +0000 2026'"""
    try:
        return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
    except (ValueError, TypeError):
        return None


def get_time_periods(dt: datetime) -> dict[str, str]:
    """Get time period keys for a datetime"""
    iso_week = dt.isocalendar()
    return {
        "year": str(dt.year),
        "month": f"{dt.year}-{dt.month:02d}",
        "week": f"{iso_week.year}-W{iso_week.week:02d}",
        "day": dt.strftime("%Y-%m-%d"),
    }


# ==================== Stories Helpers ====================

def load_stories() -> dict:
    """Load existing stories data or return empty structure"""
    if MASTER_STORIES.exists():
        with open(MASTER_STORIES, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"generated_at": None, "category_years": {}}


def save_stories(stories_data: dict) -> None:
    """Save stories data to JSON"""
    stories_data["generated_at"] = datetime.now().isoformat()
    with open(MASTER_STORIES, "w", encoding="utf-8") as f:
        json.dump(stories_data, f, indent=2, ensure_ascii=False)


def compute_tweet_hash(tweet_ids: list[str]) -> str:
    """Compute hash of tweet IDs for change detection"""
    import hashlib
    sorted_ids = ",".join(sorted(tweet_ids))
    return hashlib.md5(sorted_ids.encode()).hexdigest()[:12]


def format_story_date(date_str: str) -> str:
    """Format date string for story timeline display (e.g., 'March 5')"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        # Use %B %d and strip leading zero from day
        return dt.strftime("%B %d").replace(" 0", " ")
    except (ValueError, TypeError):
        return date_str


def get_category_year_tweets(
    cat_id: str, year: str, bookmarks: list[dict], categories_data: dict
) -> list[dict]:
    """Get all tweets for a category in a specific year"""
    cat_tweet_ids = set(categories_data.get("categories", {}).get(cat_id, {}).get("tweet_ids", []))
    result = []
    for bookmark in bookmarks:
        tweet_id = bookmark.get("Tweet Id", "")
        if tweet_id not in cat_tweet_ids:
            continue
        dt = parse_tweet_date(bookmark.get("Created At", ""))
        if dt and str(dt.year) == str(year):
            result.append(bookmark)
    # Sort by date
    result.sort(key=lambda x: parse_tweet_date(x.get("Created At", "")) or datetime.min.replace(tzinfo=None))
    return result


def should_regenerate_story(
    stories_data: dict, cat_id: str, year: str, tweet_ids: list[str], force_year: int | None = None
) -> bool:
    """Check if a category/year story needs regeneration"""
    if force_year is not None and str(force_year) == str(year):
        return True

    existing = stories_data.get("category_years", {}).get(cat_id, {}).get(str(year))
    if not existing:
        return True

    current_hash = compute_tweet_hash(tweet_ids)
    return existing.get("tweet_hash") != current_hash


def get_media_refs(tweet_ids: list[str], bookmarks: list[dict]) -> list[dict]:
    """Get media references for a list of tweet IDs"""
    media_refs = []
    tweet_lookup = {b["Tweet Id"]: b for b in bookmarks}

    for tweet_id in tweet_ids:
        tweet_media_dir = MASTER_MEDIA_DIR / tweet_id
        if tweet_media_dir.exists():
            for media_file in tweet_media_dir.iterdir():
                if media_file.is_file():
                    media_refs.append({
                        "tweet_id": tweet_id,
                        "filename": media_file.name
                    })
    return media_refs


def cluster_events(client, tweets: list[dict], category_name: str, year: str) -> list[dict]:
    """Use AI to cluster tweets into events/themes"""
    # Format tweets for prompt
    tweet_list = []
    for t in tweets[:100]:  # Limit to 100 for prompt size
        dt = parse_tweet_date(t.get("Created At", ""))
        date_str = dt.strftime("%Y-%m-%d") if dt else "unknown"
        text = t.get("Full Text", "")[:200]
        tweet_list.append(f'{t["Tweet Id"]} ({date_str}): {text}')

    prompt = f"""You are analyzing {len(tweets)} bookmarked tweets from the "{category_name}" category during {year}.

Identify 5-15 major events, themes, or narrative threads. An "event" can be:
- A specific news event covered by multiple tweets
- A recurring theme or topic
- A significant development or announcement

For each event, provide:
1. A compelling title (5-10 words)
2. Date range (earliest to latest tweet)
3. List of tweet IDs belonging to this event

Rules:
- Each tweet should belong to at most one event
- Events should have at least 3 tweets
- Order events chronologically by start date
- Not all tweets need to be assigned

Return JSON only:
{{
  "events": [
    {{
      "title": "Event Title",
      "date_start": "YYYY-MM-DD",
      "date_end": "YYYY-MM-DD",
      "tweet_ids": ["id1", "id2", ...]
    }}
  ]
}}

TWEETS:
{chr(10).join(tweet_list)}
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        result_text = response.content[0].text
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]
        result = json.loads(result_text)
        return result.get("events", [])
    except (json.JSONDecodeError, IndexError) as e:
        print(f"  Warning: Error parsing event clusters: {e}")
        return []


def generate_event_summary(client, event: dict, tweets: list[dict], category_name: str) -> str:
    """Generate AI summary for a single event"""
    tweet_texts = []
    for t in tweets[:10]:  # Limit tweets in prompt
        text = t.get("Full Text", "")[:300]
        tweet_texts.append(f"- {text}")

    prompt = f"""Write a summary for an event from someone's Twitter bookmarks.

Event Title: "{event['title']}"
Category: {category_name}
Time Period: {event.get('date_start', 'unknown')} to {event.get('date_end', 'unknown')}
Number of Bookmarks: {len(tweets)}

Tweets:
{chr(10).join(tweet_texts)}

Write a 2-4 sentence summary that:
- Captures why these tweets were bookmarked together
- Highlights notable insights or developments
- Uses engaging, narrative language

Return only the summary text."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text.strip()


def generate_year_summary(client, events: list[dict], tweets: list[dict], category_name: str, year: str) -> str:
    """Generate compelling narrative summary for a category/year"""
    # Build events overview
    events_overview = []
    for evt in events:
        events_overview.append(f"- {evt['title']} ({evt.get('date_start', '')} to {evt.get('date_end', '')}): {evt.get('summary', '')[:100]}...")

    prompt = f"""Write the opening narrative for a "story" page chronicling someone's Twitter bookmarks in "{category_name}" during {year}.

They bookmarked {len(tweets)} tweets in this category during {year}.

Major events/themes identified:
{chr(10).join(events_overview)}

Write a compelling narrative (300-400 words) that:
- Opens with a hook capturing the year's significance
- Weaves the major themes into a coherent story
- Highlights patterns or evolution across the year
- Uses vivid, engaging prose
- Ends with a reflective note

Return only the narrative text."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text.strip()


def generate_story(client, stories_data: dict, cat_id: str, year: str,
                   bookmarks: list[dict], categories_data: dict) -> None:
    """Generate complete story for a category/year"""
    cat_name = categories_data.get("categories", {}).get(cat_id, {}).get("name", cat_id)

    # Get tweets for this category/year
    tweets = get_category_year_tweets(cat_id, year, bookmarks, categories_data)
    if not tweets:
        print(f"  No tweets found for {cat_id}/{year}")
        return

    print(f"  Clustering {len(tweets)} tweets into events...")
    events_raw = cluster_events(client, tweets, cat_name, year)
    print(f"  Found {len(events_raw)} events")

    # Build tweet lookup for this set
    tweet_lookup = {t["Tweet Id"]: t for t in tweets}

    # Generate summaries for each event
    events = []
    for i, evt_raw in enumerate(events_raw, 1):
        print(f"  Generating summary for event {i}/{len(events_raw)}: {evt_raw.get('title', 'Untitled')[:40]}...")
        evt_tweets = [tweet_lookup[tid] for tid in evt_raw.get("tweet_ids", []) if tid in tweet_lookup]

        if len(evt_tweets) < 3:
            continue

        summary = generate_event_summary(client, evt_raw, evt_tweets, cat_name)

        events.append({
            "id": f"evt-{len(events)+1:03d}",
            "title": evt_raw.get("title", "Untitled Event"),
            "summary": summary,
            "date_start": evt_raw.get("date_start", ""),
            "date_end": evt_raw.get("date_end", ""),
            "tweet_ids": evt_raw.get("tweet_ids", []),
            "media_refs": get_media_refs(evt_raw.get("tweet_ids", []), bookmarks),
            "tweet_count": len(evt_tweets)
        })

    # Generate year summary
    print(f"  Generating year summary...")
    year_summary = generate_year_summary(client, events, tweets, cat_name, year)

    # Store in stories_data
    if cat_id not in stories_data["category_years"]:
        stories_data["category_years"][cat_id] = {}

    stories_data["category_years"][cat_id][year] = {
        "generated_at": datetime.now().isoformat(),
        "tweet_count": len(tweets),
        "tweet_hash": compute_tweet_hash([t["Tweet Id"] for t in tweets]),
        "summary": year_summary,
        "events": events
    }

    print(f"  Story complete: {len(events)} events, {len(tweets)} tweets")


def cmd_categorize(args: argparse.Namespace) -> None:
    """Categorize bookmarks using Claude API"""
    print("=== Categorizing bookmarks ===")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Set it with: export ANTHROPIC_API_KEY='your-key-here'")
        return

    if not MASTER_JSON.exists():
        print(f"Master JSON not found. Run 'merge' first.")
        return

    with open(MASTER_JSON, "r", encoding="utf-8") as f:
        bookmarks = json.load(f)

    print(f"Loaded {len(bookmarks)} bookmarks")

    try:
        import anthropic
    except ImportError:
        print("Error: anthropic package not installed")
        print("Install with: pip install anthropic")
        return

    client = anthropic.Anthropic(api_key=api_key)

    # Phase 1: Discover categories from a sample
    print("\nPhase 1: Discovering category taxonomy...")
    sample_size = min(100, len(bookmarks))
    sample_texts = [b.get("Full Text", "")[:500] for b in bookmarks[:sample_size]]

    taxonomy_prompt = f"""Analyze these {sample_size} Twitter bookmarks and create a category taxonomy.

Create 10-20 categories that would help organize these bookmarks. Categories should be:
- Specific enough to be useful (not just "Technology")
- Broad enough to contain multiple tweets
- Use kebab-case for category IDs

Return JSON only, no other text:
{{
  "categories": {{
    "category-id": {{
      "name": "Human Readable Name",
      "description": "Brief description of what belongs here"
    }}
  }}
}}

Sample tweets:
{chr(10).join(f'- {t[:200]}...' for t in sample_texts[:30])}
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": taxonomy_prompt}]
    )

    try:
        taxonomy_text = response.content[0].text
        # Extract JSON from response
        if "```json" in taxonomy_text:
            taxonomy_text = taxonomy_text.split("```json")[1].split("```")[0]
        elif "```" in taxonomy_text:
            taxonomy_text = taxonomy_text.split("```")[1].split("```")[0]
        taxonomy = json.loads(taxonomy_text)
        categories = taxonomy.get("categories", {})
    except (json.JSONDecodeError, IndexError) as e:
        print(f"Error parsing taxonomy: {e}")
        print(f"Response: {response.content[0].text[:500]}")
        return

    print(f"Discovered {len(categories)} categories:")
    for cat_id, cat_info in categories.items():
        print(f"  - {cat_id}: {cat_info.get('name', cat_id)}")

    # Phase 2: Categorize all tweets in batches
    print("\nPhase 2: Categorizing tweets...")
    tweet_categories: dict[str, list[str]] = {}
    category_tweets: dict[str, list[str]] = defaultdict(list)

    batch_size = 20
    category_list = ", ".join(categories.keys())

    for i in range(0, len(bookmarks), batch_size):
        batch = bookmarks[i:i + batch_size]
        print(f"Processing batch {i // batch_size + 1}/{(len(bookmarks) + batch_size - 1) // batch_size}...")

        batch_prompt = f"""Categorize these tweets. Available categories: {category_list}

Assign 1-3 categories to each tweet. Return JSON only:
{{"tweet_id": ["category1", "category2"]}}

Tweets:
"""
        for b in batch:
            batch_prompt += f'\n{b.get("Tweet Id")}: {b.get("Full Text", "")[:300]}'

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": batch_prompt}]
        )

        try:
            result_text = response.content[0].text
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]
            batch_results = json.loads(result_text)

            for tweet_id, cats in batch_results.items():
                tweet_categories[tweet_id] = cats
                for cat in cats:
                    if cat in categories:
                        category_tweets[cat].append(tweet_id)
        except (json.JSONDecodeError, IndexError) as e:
            print(f"  Warning: Error parsing batch: {e}")

    # Phase 3: Generate summaries per category per time period
    print("\nPhase 3: Generating category summaries...")

    # Build tweet lookup
    tweet_lookup = {b["Tweet Id"]: b for b in bookmarks}

    # Group tweets by category and time period
    category_summaries: dict[str, dict[str, str]] = defaultdict(dict)

    # Pre-calculate total summaries to generate for progress
    summary_tasks = []
    for cat_id, tweet_ids in category_tweets.items():
        if not tweet_ids:
            continue
        cat_tweets = [tweet_lookup.get(tid) for tid in tweet_ids if tid in tweet_lookup]
        cat_tweets = [t for t in cat_tweets if t]
        if not cat_tweets:
            continue
        by_period_temp: dict[str, list[dict]] = defaultdict(list)
        for tweet in cat_tweets:
            dt = parse_tweet_date(tweet.get("Created At", ""))
            if dt:
                periods = get_time_periods(dt)
                by_period_temp[periods["year"]].append(tweet)
                by_period_temp[periods["month"]].append(tweet)
        for period, period_tweets in by_period_temp.items():
            if len(period_tweets) >= 3:
                summary_tasks.append((cat_id, period, period_tweets))

    total_summaries = len(summary_tasks)
    print(f"Generating {total_summaries} summaries...")

    for idx, (cat_id, period, period_tweets) in enumerate(summary_tasks, 1):
        print(f"  Summary {idx}/{total_summaries}: {categories[cat_id].get('name', cat_id)} - {period}")

        summary_prompt = f"""Summarize these {len(period_tweets)} bookmarked tweets in the "{categories[cat_id].get('name', cat_id)}" category from {period}.

Keep it to 2-3 sentences highlighting key themes and notable content.

Tweets:
{chr(10).join(t.get('Full Text', '')[:200] for t in period_tweets[:15])}
"""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": summary_prompt}]
        )

        category_summaries[cat_id][period] = response.content[0].text.strip()

    # Build final categories structure
    final_categories = {
        "categories": {},
        "tweet_categories": tweet_categories
    }

    for cat_id, cat_info in categories.items():
        final_categories["categories"][cat_id] = {
            "name": cat_info.get("name", cat_id),
            "description": cat_info.get("description", ""),
            "tweet_ids": category_tweets.get(cat_id, []),
            "summaries": category_summaries.get(cat_id, {})
        }

    # Write categories JSON
    with open(MASTER_CATEGORIES, "w", encoding="utf-8") as f:
        json.dump(final_categories, f, indent=2, ensure_ascii=False)

    print(f"\nWritten to {MASTER_CATEGORIES}")
    print(f"Categorized {len(tweet_categories)} tweets into {len(categories)} categories")


# HTML Templates
HTML_BASE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        :root {{
            --bg: #fff;
            --text: #1a1a1a;
            --secondary: #666;
            --border: #e1e1e1;
            --link: #1d9bf0;
            --card-bg: #f7f7f7;
        }}
        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg: #15202b;
                --text: #e7e9ea;
                --secondary: #8b98a5;
                --border: #38444d;
                --link: #1d9bf0;
                --card-bg: #1e2732;
            }}
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
            padding: 20px;
            max-width: 800px;
            margin: 0 auto;
        }}
        a {{ color: var(--link); text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        nav {{
            position: sticky;
            top: 0;
            background: var(--bg);
            z-index: 100;
            margin-bottom: 20px;
            padding: 15px 0 10px;
            border-bottom: 1px solid var(--border);
        }}
        nav a {{ margin-right: 15px; }}
        h1 {{ margin-bottom: 10px; }}
        h2 {{ margin: 20px 0 10px; font-size: 1.3em; }}
        .meta {{ color: var(--secondary); font-size: 0.9em; margin-bottom: 20px; }}
        .tweet-card {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 15px;
            margin-bottom: 15px;
        }}
        .tweet-header {{
            display: flex;
            align-items: center;
            margin-bottom: 10px;
        }}
        .avatar {{
            width: 48px;
            height: 48px;
            border-radius: 50%;
            margin-right: 10px;
        }}
        .author-info {{ flex: 1; }}
        .author-name {{ font-weight: bold; }}
        .author-handle {{ color: var(--secondary); }}
        .tweet-text {{
            margin-bottom: 15px;
            white-space: pre-wrap;
            word-break: break-word;
        }}
        .tweet-media {{
            margin-bottom: 15px;
        }}
        .tweet-media img {{
            max-width: 100%;
            border-radius: 12px;
            margin-bottom: 10px;
        }}
        .tweet-media video {{
            max-width: 100%;
            border-radius: 12px;
        }}
        .tweet-stats {{
            color: var(--secondary);
            font-size: 0.85em;
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
        }}
        .tweet-links {{
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid var(--border);
        }}
        .category-tag {{
            display: inline-block;
            background: var(--link);
            color: white;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.8em;
            margin-right: 5px;
            margin-bottom: 5px;
        }}
        .summary {{
            background: var(--card-bg);
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-style: italic;
        }}
        .search-box {{
            width: 100%;
            padding: 10px;
            margin-bottom: 20px;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: var(--card-bg);
            color: var(--text);
            font-size: 1em;
        }}
        .search-container {{
            position: relative;
        }}
        .search-results {{
            color: var(--secondary);
            font-size: 0.9em;
            margin-bottom: 15px;
        }}
        .search-suggestions {{
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 0 0 8px 8px;
            max-height: 200px;
            overflow-y: auto;
            z-index: 50;
        }}
        .search-suggestions div {{
            padding: 8px 10px;
            cursor: pointer;
        }}
        .search-suggestions div:hover,
        .search-suggestions div.selected {{
            background: var(--link);
            color: white;
        }}
        .search-suggestions .match-count {{
            color: var(--secondary);
            font-size: 0.8em;
            float: right;
        }}
        .timeline-nav {{
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid var(--border);
        }}
        .year-row, .month-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .year-link, .month-link {{
            cursor: pointer;
            color: var(--link);
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.85em;
        }}
        .year-link:hover, .month-link:hover {{
            background: var(--link);
            color: white;
        }}
        .year-link.active {{
            background: var(--link);
            color: white;
        }}
        .month-row {{
            margin-top: 8px;
            padding: 8px;
            background: var(--bg);
            border-radius: 4px;
        }}
        .filter-bar, .month-filter {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 15px;
        }}
        .filter-btn {{
            padding: 6px 12px;
            border: 1px solid var(--border);
            border-radius: 20px;
            background: var(--card-bg);
            color: var(--text);
            cursor: pointer;
            font-size: 0.85em;
        }}
        .filter-btn:hover {{
            border-color: var(--link);
        }}
        .filter-btn.active {{
            background: var(--link);
            color: white;
            border-color: var(--link);
        }}
        /* Story styles */
        .summary-narrative {{
            font-size: 1.05em;
            line-height: 1.7;
            margin-bottom: 30px;
            padding: 20px;
            background: var(--card-bg);
            border-radius: 12px;
        }}
        .story-timeline {{
            position: relative;
            padding: 20px 0;
            margin: 30px 0;
        }}
        .timeline-line {{
            position: absolute;
            left: 20px;
            top: 0;
            bottom: 0;
            width: 2px;
            background: var(--border);
        }}
        .timeline-event {{
            position: relative;
            margin-left: 50px;
            margin-bottom: 20px;
        }}
        .event-dot {{
            position: absolute;
            left: -38px;
            top: 15px;
            width: 14px;
            height: 14px;
            border-radius: 50%;
            background: var(--link);
            border: 3px solid var(--bg);
        }}
        .event-card {{
            background: var(--card-bg);
            border-radius: 12px;
            overflow: hidden;
        }}
        .event-header {{
            padding: 15px;
            cursor: pointer;
            display: flex;
            flex-wrap: wrap;
            align-items: baseline;
            gap: 10px;
        }}
        .event-header:hover {{
            background: rgba(29, 155, 240, 0.1);
        }}
        .event-date {{
            color: var(--secondary);
            font-size: 0.85em;
            min-width: 120px;
        }}
        .event-title {{
            flex: 1;
            margin: 0;
            font-size: 1.1em;
        }}
        .event-count {{
            color: var(--secondary);
            font-size: 0.85em;
        }}
        .event-content {{
            display: none;
            padding: 0 15px 15px;
            border-top: 1px solid var(--border);
        }}
        .event-card.expanded .event-content {{
            display: block;
        }}
        .event-summary {{
            margin-bottom: 15px;
        }}
        .event-media {{
            display: flex;
            gap: 10px;
            overflow-x: auto;
            padding: 10px 0;
        }}
        .event-media img, .event-media video {{
            height: 100px;
            border-radius: 8px;
            flex-shrink: 0;
        }}
        .event-tweets-link {{
            display: inline-block;
            margin-top: 10px;
        }}
        .stories-toc {{
            display: grid;
            gap: 20px;
        }}
        .category-section {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 15px 20px;
        }}
        .category-section h3 {{
            margin: 0 0 10px;
        }}
        .year-links {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .year-links a {{
            padding: 5px 12px;
            background: var(--bg);
            border-radius: 20px;
            font-size: 0.9em;
        }}
        /* Collapsible bookmark sections */
        .bookmark-section {{
            margin-bottom: 10px;
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
        }}
        .section-header {{
            position: sticky;
            top: 0;
            background: var(--card-bg);
            padding: 12px 15px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            z-index: 10;
            border-bottom: 1px solid var(--border);
        }}
        .section-header:hover {{
            background: rgba(29, 155, 240, 0.1);
        }}
        .section-toggle {{
            transition: transform 0.2s;
            font-size: 0.8em;
        }}
        .bookmark-section:not(.collapsed) .section-toggle {{
            transform: rotate(90deg);
        }}
        .section-title {{
            font-weight: 600;
            flex: 1;
        }}
        .section-count {{
            color: var(--secondary);
            font-size: 0.9em;
        }}
        .section-content {{
            display: none;
        }}
        .bookmark-section:not(.collapsed) .section-content {{
            display: block;
        }}
        .bookmark-section:not(.collapsed) .section-header {{
            border-bottom: 1px solid var(--border);
        }}
        .bookmark-section.collapsed .section-header {{
            border-bottom: none;
        }}
        .hidden {{ display: none; }}
    </style>
</head>
<body>
    <nav>
        <a href="../index.html">Chronological</a>
        <a href="../categories/index.html">Categories</a>
        <a href="../timeline/index.html">Timeline</a>
        <a href="../stories/index.html">Stories</a>
    </nav>
    {content}
    <script>
    // Toggle collapsible bookmark sections
    function toggleSection(header) {{
        const section = header.closest('.bookmark-section');
        section.classList.toggle('collapsed');
    }}

    // Open a specific section and scroll to it
    function openSection(eventId) {{
        const section = document.getElementById('section-' + eventId);
        if (section) {{
            section.classList.remove('collapsed');
            setTimeout(() => section.scrollIntoView({{behavior: 'smooth', block: 'start'}}), 100);
        }}
    }}

    // Handle hash navigation on page load
    document.addEventListener('DOMContentLoaded', function() {{
        if (window.location.hash && window.location.hash.startsWith('#section-')) {{
            const sectionId = window.location.hash.substring(1);
            const section = document.getElementById(sectionId);
            if (section) {{
                section.classList.remove('collapsed');
                setTimeout(() => section.scrollIntoView({{behavior: 'smooth', block: 'start'}}), 100);
            }}
        }}
    }});
    </script>
</body>
</html>
"""

TWEET_TEMPLATE = """
<article class="tweet-card" data-text="{search_text}">
    <div class="tweet-header">
        <img class="avatar" src="{avatar_url}" alt="{name}" onerror="this.style.display='none'">
        <div class="author-info">
            <div class="author-name">{name}</div>
            <div class="author-handle">
                <a href="https://x.com/{screen_name}" target="_blank">@{screen_name}</a>
            </div>
        </div>
    </div>
    <div class="tweet-text">{text}</div>
    {media_html}
    {categories_html}
    <div class="tweet-stats">
        <span>{likes} likes</span>
        <span>{retweets} retweets</span>
        <span>{replies} replies</span>
        <span>{date}</span>
    </div>
    <div class="tweet-links">
        <a href="https://x.com/{screen_name}/status/{tweet_id}" target="_blank">View on X</a>
        {detail_link}
    </div>
</article>
"""


def render_media_html(tweet_id: str, media_dir: Path) -> str:
    """Render HTML for tweet media using local files"""
    tweet_media_dir = media_dir / tweet_id
    if not tweet_media_dir.exists():
        return ""

    media_files = list(tweet_media_dir.iterdir())
    if not media_files:
        return ""

    html_parts = ['<div class="tweet-media">']
    for media_file in media_files:
        rel_path = f"../../media/{tweet_id}/{media_file.name}"
        if media_file.suffix.lower() in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
            html_parts.append(f'<img src="{rel_path}" alt="Tweet media" loading="lazy">')
        elif media_file.suffix.lower() in [".mp4", ".webm", ".mov"]:
            html_parts.append(f'<video src="{rel_path}" controls preload="metadata"></video>')
    html_parts.append('</div>')

    return "\n".join(html_parts) if len(html_parts) > 2 else ""


def render_media_html_cdn(bookmark: dict) -> str:
    """Render HTML for tweet media using Twitter CDN URLs"""
    media_urls = bookmark.get("Media URLs", "")
    media_types = bookmark.get("Media Types", "")

    if not media_urls:
        return ""

    urls = [u.strip() for u in media_urls.split(",") if u.strip()]
    types = [t.strip() for t in media_types.split(",")] if media_types else []

    if not urls:
        return ""

    html_parts = ['<div class="tweet-media">']
    for i, url in enumerate(urls):
        media_type = types[i] if i < len(types) else ""
        if media_type == "video" or any(ext in url.lower() for ext in ['.mp4', '.webm', '.mov']):
            html_parts.append(f'<video src="{url}" controls preload="metadata"></video>')
        else:
            html_parts.append(f'<img src="{url}" alt="Tweet media" loading="lazy">')
    html_parts.append('</div>')

    return "\n".join(html_parts) if len(html_parts) > 2 else ""


def render_tweet_card(bookmark: dict, categories_data: dict | None = None,
                      include_detail_link: bool = True, use_cdn: bool = False) -> str:
    """Render a tweet card HTML. If use_cdn=True, uses Twitter CDN URLs for media."""
    tweet_id = bookmark.get("Tweet Id", "")

    # Get categories for this tweet
    categories_html = ""
    if categories_data:
        tweet_cats = categories_data.get("tweet_categories", {}).get(tweet_id, [])
        if tweet_cats:
            cat_tags = []
            for cat_id in tweet_cats:
                cat_name = categories_data.get("categories", {}).get(cat_id, {}).get("name", cat_id)
                cat_tags.append(f'<a href="../categories/{cat_id}.html" class="category-tag">{cat_name}</a>')
            categories_html = f'<div class="tweet-categories">{" ".join(cat_tags)}</div>'

    # Parse date
    date_str = bookmark.get("Created At", "")
    try:
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        formatted_date = dt.strftime("%b %d, %Y at %H:%M")
    except ValueError:
        formatted_date = date_str

    detail_link = f' | <a href="../tweets/{tweet_id}.html">Details</a>' if include_detail_link else ""

    # Use CDN or local media
    if use_cdn:
        media_html = render_media_html_cdn(bookmark)
    else:
        media_html = render_media_html(tweet_id, MASTER_MEDIA_DIR)

    return TWEET_TEMPLATE.format(
        tweet_id=tweet_id,
        avatar_url=bookmark.get("User Avatar Url", ""),
        name=bookmark.get("User Name", "Unknown"),
        screen_name=bookmark.get("User Screen Name", "unknown"),
        text=bookmark.get("Full Text", ""),
        media_html=media_html,
        categories_html=categories_html,
        likes=bookmark.get("Favorite Count", 0),
        retweets=bookmark.get("Retweet Count", 0),
        replies=bookmark.get("Reply Count", 0),
        date=formatted_date,
        detail_link=detail_link,
        search_text=bookmark.get("Full Text", "").lower().replace('"', '&quot;')[:500]
    )


def build_category_timeline(bookmarks: list[dict], categories_data: dict) -> dict:
    """Build timeline data for each category: {cat_id: {year: {month: count}}}"""
    timeline = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    if not categories_data:
        return {}

    tweet_categories = categories_data.get("tweet_categories", {})
    tweet_lookup = {b["Tweet Id"]: b for b in bookmarks}

    for tweet_id, cats in tweet_categories.items():
        bookmark = tweet_lookup.get(tweet_id)
        if not bookmark:
            continue

        dt = parse_tweet_date(bookmark.get("Created At", ""))
        if not dt:
            continue

        year = str(dt.year)
        month = f"{dt.month:02d}"

        for cat in cats:
            timeline[cat][year][month] += 1

    # Convert to regular dict for JSON serialization
    return {
        cat: {year: dict(months) for year, months in years.items()}
        for cat, years in timeline.items()
    }


def build_search_index(bookmarks: list[dict], show_progress: bool = True) -> dict:
    """Build search index for client-side search with autocomplete"""
    import re

    # Stopwords to exclude from word index
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
        'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
        'dare', 'ought', 'used', 'it', 'its', 'this', 'that', 'these', 'those',
        'i', 'you', 'he', 'she', 'we', 'they', 'what', 'which', 'who', 'whom',
        'whose', 'where', 'when', 'why', 'how', 'all', 'each', 'every', 'both',
        'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
        'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'also',
        'now', 'here', 'there', 'then', 'once', 'if', 'unless', 'until',
        'while', 'about', 'after', 'before', 'between', 'into', 'through',
        'during', 'above', 'below', 'up', 'down', 'out', 'off', 'over', 'under',
        'again', 'further', 'https', 'http', 'com', 'www', 't', 'co', 's', 're'
    }

    words_index: dict[str, list[str]] = defaultdict(list)
    profiles_index: dict[str, list[str]] = defaultdict(list)
    word_counts: dict[str, int] = defaultdict(int)
    profile_counts: dict[str, int] = defaultdict(int)
    tweets_meta: dict[str, dict] = {}

    total = len(bookmarks)
    if show_progress:
        print(f"Building search index for {total} bookmarks...")

    for idx, bookmark in enumerate(bookmarks, 1):
        if show_progress and idx % 500 == 0:
            print(f"  Indexed {idx}/{total} bookmarks ({idx * 100 // total}%)")
        tweet_id = bookmark.get("Tweet Id", "")
        if not tweet_id:
            continue

        text = bookmark.get("Full Text", "")
        author = bookmark.get("User Screen Name", "")
        name = bookmark.get("User Name", "")
        date = bookmark.get("Created At", "")

        # Parse date for display
        dt = parse_tweet_date(date)
        date_str = dt.strftime("%Y-%m-%d") if dt else ""

        # Store tweet metadata (truncated for size)
        tweets_meta[tweet_id] = {
            "t": text[:100] + "..." if len(text) > 100 else text,
            "a": f"@{author}",
            "d": date_str
        }

        # Index author
        if author:
            author_lower = author.lower()
            if tweet_id not in profiles_index[author_lower]:
                profiles_index[author_lower].append(tweet_id)
                profile_counts[author_lower] += 1

        # Extract and index words
        words = re.findall(r'[a-zA-Z]{3,}', text.lower())
        seen_words = set()
        for word in words:
            if word not in stopwords and word not in seen_words:
                seen_words.add(word)
                words_index[word].append(tweet_id)
                word_counts[word] += 1

        # Extract mentioned @handles
        mentions = re.findall(r'@([a-zA-Z0-9_]+)', text)
        for mention in mentions:
            mention_lower = mention.lower()
            if tweet_id not in profiles_index[mention_lower]:
                profiles_index[mention_lower].append(tweet_id)
                profile_counts[mention_lower] += 1

    # Get all words and profiles for suggestions (sorted by frequency)
    top_words = sorted(word_counts.keys(), key=lambda w: word_counts[w], reverse=True)
    top_profiles = sorted(profile_counts.keys(), key=lambda p: profile_counts[p], reverse=True)

    # Only keep words that appear in multiple tweets for the index
    filtered_words = {w: ids for w, ids in words_index.items() if len(ids) >= 2}

    if show_progress:
        print(f"  Done: {len(filtered_words)} words, {len(profiles_index)} profiles indexed")

    return {
        "words": {w: filtered_words[w] for w in top_words if w in filtered_words},
        "profiles": dict(profiles_index),
        "tweets": tweets_meta,
        "suggestions": {
            "words": [w for w in top_words if w in filtered_words],
            "profiles": [f"@{p}" for p in top_profiles]
        }
    }


# ==================== Story HTML Generation ====================

def generate_stories_index(stories_data: dict, categories_data: dict) -> None:
    """Generate the stories index page (table of contents)"""
    stories_dir = MASTER_HTML_DIR / "stories"
    stories_dir.mkdir(parents=True, exist_ok=True)

    categories = categories_data.get("categories", {})
    category_years = stories_data.get("category_years", {})

    # Build TOC content
    toc_html = '<div class="stories-toc">\n'

    # Sort categories by number of stories
    sorted_cats = sorted(
        category_years.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )

    for cat_id, years in sorted_cats:
        cat_name = categories.get(cat_id, {}).get("name", cat_id)
        sorted_years = sorted(years.keys(), reverse=True)

        year_links = []
        for year in sorted_years:
            tweet_count = years[year].get("tweet_count", 0)
            year_links.append(f'<a href="{cat_id}/{year}.html">{year} ({tweet_count} bookmarks)</a>')

        toc_html += f'''
<div class="category-section">
    <h3><a href="../categories/{cat_id}.html">{cat_name}</a></h3>
    <div class="year-links">
        {chr(10).join(year_links)}
    </div>
</div>
'''

    toc_html += '</div>'

    content = f'''
<h1>Stories</h1>
<p class="meta">AI-generated narratives of your bookmarks by category and year</p>
{toc_html}
'''

    page_html = HTML_BASE.format(title="Stories", content=content)
    page_html = page_html.replace('../stories/', '')

    with open(stories_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(page_html)


def generate_story_page(cat_id: str, year: str, story: dict,
                        bookmarks: list[dict], categories_data: dict) -> None:
    """Generate a single story page with timeline"""
    stories_dir = MASTER_HTML_DIR / "stories" / cat_id
    stories_dir.mkdir(parents=True, exist_ok=True)

    cat_name = categories_data.get("categories", {}).get(cat_id, {}).get("name", cat_id)
    tweet_lookup = {b["Tweet Id"]: b for b in bookmarks}

    # Build timeline HTML
    timeline_html = '<div class="story-timeline">\n<div class="timeline-line"></div>\n'

    events = story.get("events", [])
    for evt in events:
        # Format date range (e.g., "March 13 → April 4")
        date_start = evt.get("date_start", "")
        date_end = evt.get("date_end", "")
        if date_start == date_end:
            date_display = format_story_date(date_start)
        else:
            date_display = f"{format_story_date(date_start)} → {format_story_date(date_end)}"

        # Build media preview
        media_html = ""
        media_refs = evt.get("media_refs", [])[:4]  # Limit to 4 media items
        if media_refs:
            media_items = []
            for ref in media_refs:
                media_path = f"../../media/{ref['tweet_id']}/{ref['filename']}"
                if ref['filename'].lower().endswith(('.mp4', '.webm', '.mov')):
                    media_items.append(f'<video src="{media_path}" preload="metadata"></video>')
                else:
                    media_items.append(f'<img src="{media_path}" loading="lazy">')
            media_html = f'<div class="event-media">{chr(10).join(media_items)}</div>'

        timeline_html += f'''
<div class="timeline-event" data-event-id="{evt['id']}">
    <div class="event-dot"></div>
    <div class="event-card">
        <div class="event-header" onclick="this.parentElement.classList.toggle('expanded')">
            <span class="event-date">{date_display}</span>
            <h3 class="event-title">{evt.get('title', 'Untitled')}</h3>
            <span class="event-count">{evt.get('tweet_count', 0)} bookmarks</span>
        </div>
        <div class="event-content">
            <p class="event-summary">{evt.get('summary', '')}</p>
            {media_html}
            <a href="#section-{evt['id']}" class="event-tweets-link" onclick="openSection('{evt['id']}')">View tweets below</a>
        </div>
    </div>
</div>
'''

    timeline_html += '</div>'

    # Build tweets section grouped by event (collapsible sections)
    tweets_html = ""
    all_event_tweet_ids = set()

    for evt in events:
        evt_tweet_ids = evt.get("tweet_ids", [])
        all_event_tweet_ids.update(evt_tweet_ids)

        section_content = ""
        for tid in evt_tweet_ids:
            if tid in tweet_lookup:
                section_content += render_tweet_card(tweet_lookup[tid], categories_data)

        evt_count = len(evt_tweet_ids)
        tweets_html += f'''<div class="bookmark-section collapsed" id="section-{evt["id"]}">
    <div class="section-header" onclick="toggleSection(this)">
        <span class="section-toggle">▶</span>
        <span class="section-title">{evt.get("title", "Untitled")}</span>
        <span class="section-count">({evt_count} bookmarks)</span>
    </div>
    <div class="section-content">
{section_content}
    </div>
</div>
'''

    # Add uncategorized tweets
    cat_tweet_ids = set(categories_data.get("categories", {}).get(cat_id, {}).get("tweet_ids", []))
    uncategorized = []
    for bookmark in bookmarks:
        tid = bookmark.get("Tweet Id", "")
        if tid in cat_tweet_ids and tid not in all_event_tweet_ids:
            dt = parse_tweet_date(bookmark.get("Created At", ""))
            if dt and str(dt.year) == str(year):
                uncategorized.append(bookmark)

    if uncategorized:
        section_content = ""
        for bookmark in uncategorized:
            section_content += render_tweet_card(bookmark, categories_data)

        tweets_html += f'''<div class="bookmark-section collapsed" id="section-other">
    <div class="section-header" onclick="toggleSection(this)">
        <span class="section-toggle">▶</span>
        <span class="section-title">Other Bookmarks</span>
        <span class="section-count">({len(uncategorized)} bookmarks)</span>
    </div>
    <div class="section-content">
{section_content}
    </div>
</div>
'''

    # Assemble page
    content = f'''
<h1>{cat_name} - {year}</h1>
<p class="meta">{story.get('tweet_count', 0)} bookmarks | Generated {story.get('generated_at', '')[:10]}</p>

<div class="summary-narrative">
{markdown.markdown(story.get('summary', ''))}
</div>

<h2>Timeline of Events</h2>
{timeline_html}

<h2>All Bookmarks</h2>
{tweets_html}
'''

    page_html = HTML_BASE.format(title=f"{cat_name} - {year}", content=content)
    # Fix paths for stories/cat/year.html depth
    page_html = page_html.replace('../index.html', '../../index.html')
    page_html = page_html.replace('../categories/', '../../categories/')
    page_html = page_html.replace('../timeline/', '../../timeline/')
    page_html = page_html.replace('../stories/', '../../stories/')
    page_html = page_html.replace('../tweets/', '../../tweets/')
    page_html = page_html.replace('../../media/', '../../../media/')

    with open(stories_dir / f"{year}.html", "w", encoding="utf-8") as f:
        f.write(page_html)


def generate_story_pages(bookmarks: list[dict], categories_data: dict, stories_data: dict) -> None:
    """Generate all story HTML pages"""
    if not stories_data.get("category_years"):
        return

    # Generate index
    generate_stories_index(stories_data, categories_data)

    # Generate individual story pages
    for cat_id, years in stories_data.get("category_years", {}).items():
        for year, story in years.items():
            generate_story_page(cat_id, year, story, bookmarks, categories_data)


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate HTML pages"""
    print("=== Generating HTML pages ===")

    if not MASTER_JSON.exists():
        print(f"Master JSON not found. Run 'merge' first.")
        return

    with open(MASTER_JSON, "r", encoding="utf-8") as f:
        bookmarks = json.load(f)

    # Load categories if available
    categories_data = None
    if MASTER_CATEGORIES.exists():
        with open(MASTER_CATEGORIES, "r", encoding="utf-8") as f:
            categories_data = json.load(f)

    # Ensure directories exist
    (MASTER_HTML_DIR / "tweets").mkdir(parents=True, exist_ok=True)
    (MASTER_HTML_DIR / "categories").mkdir(parents=True, exist_ok=True)
    (MASTER_HTML_DIR / "timeline").mkdir(parents=True, exist_ok=True)
    (MASTER_HTML_DIR / "timeline" / "daily").mkdir(parents=True, exist_ok=True)

    # Build tweet lookup
    tweet_lookup = {b["Tweet Id"]: b for b in bookmarks}

    # Build category timeline data
    category_timeline = {}
    if categories_data:
        print("Building category timeline data...")
        category_timeline = build_category_timeline(bookmarks, categories_data)

    # Build search index
    search_index = build_search_index(bookmarks)

    # Generate individual tweet pages
    print(f"Generating {len(bookmarks)} tweet pages...")
    for bookmark in bookmarks:
        tweet_id = bookmark.get("Tweet Id", "")
        if not tweet_id:
            continue

        tweet_html = render_tweet_card(bookmark, categories_data, include_detail_link=False)
        content = f"<h1>Tweet by @{bookmark.get('User Screen Name', 'unknown')}</h1>{tweet_html}"

        page_html = HTML_BASE.format(
            title=f"Tweet by @{bookmark.get('User Screen Name', 'unknown')}",
            content=content
        )

        with open(MASTER_HTML_DIR / "tweets" / f"{tweet_id}.html", "w", encoding="utf-8") as f:
            f.write(page_html)

    # Generate main index (chronological) with search
    print("Generating main index...")

    # Create compact search index for embedding (suggestions only, no full index)
    search_suggestions = json.dumps(search_index.get("suggestions", {}))
    tweets_html = "\n".join(render_tweet_card(b, categories_data) for b in bookmarks)

    index_content = f"""
<h1>Twitter Bookmarks</h1>
<p class="meta">{len(bookmarks)} bookmarks</p>
<div class="search-container">
    <input type="text" id="search-input" class="search-box" placeholder="Search tweets... (type @ for profiles)" autocomplete="off">
    <div id="search-suggestions" class="search-suggestions hidden"></div>
</div>
<div id="search-results" class="search-results hidden"></div>
<div id="tweets-container">
{tweets_html}
</div>
<script>
const SUGGESTIONS = {search_suggestions};
const searchInput = document.getElementById('search-input');
const suggestionsDiv = document.getElementById('search-suggestions');
let selectedIdx = -1;

function showSuggestions(query) {{
    if (!query || query.length < 2) {{
        suggestionsDiv.classList.add('hidden');
        return;
    }}

    const isProfile = query.startsWith('@');
    const searchTerm = isProfile ? query.slice(1).toLowerCase() : query.toLowerCase();
    const source = isProfile ? SUGGESTIONS.profiles : SUGGESTIONS.words;

    const matches = source.filter(s => {{
        const term = isProfile ? s.slice(1).toLowerCase() : s.toLowerCase();
        return term.includes(searchTerm);
    }}).slice(0, 8);

    if (matches.length === 0) {{
        suggestionsDiv.classList.add('hidden');
        return;
    }}

    suggestionsDiv.innerHTML = matches.map((m, i) =>
        `<div data-value="${{m}}" class="${{i === selectedIdx ? 'selected' : ''}}">${{m}}</div>`
    ).join('');
    suggestionsDiv.classList.remove('hidden');
    selectedIdx = -1;

    suggestionsDiv.querySelectorAll('div').forEach(div => {{
        div.addEventListener('click', () => {{
            searchInput.value = div.dataset.value;
            suggestionsDiv.classList.add('hidden');
            filterTweets(div.dataset.value);
        }});
    }});
}}

function filterTweets(query) {{
    query = query.toLowerCase();
    const isProfile = query.startsWith('@');
    const searchTerm = isProfile ? query.slice(1) : query;
    const resultsDiv = document.getElementById('search-results');
    let matchCount = 0;

    document.querySelectorAll('.tweet-card').forEach(card => {{
        const text = card.dataset.text || '';
        let show = !query;
        if (isProfile) {{
            const handle = card.querySelector('.author-handle a')?.textContent?.toLowerCase() || '';
            show = handle.includes(searchTerm);
        }} else {{
            show = text.includes(searchTerm);
        }}
        card.classList.toggle('hidden', !show);
        if (show) matchCount++;
    }});

    if (query) {{
        resultsDiv.textContent = `${{matchCount}} bookmark${{matchCount !== 1 ? 's' : ''}} found`;
        resultsDiv.classList.remove('hidden');
    }} else {{
        resultsDiv.classList.add('hidden');
    }}
}}

searchInput.addEventListener('input', (e) => {{
    showSuggestions(e.target.value);
    filterTweets(e.target.value);
}});

searchInput.addEventListener('keydown', (e) => {{
    const items = suggestionsDiv.querySelectorAll('div');
    if (e.key === 'ArrowDown') {{
        e.preventDefault();
        selectedIdx = Math.min(selectedIdx + 1, items.length - 1);
        items.forEach((item, i) => item.classList.toggle('selected', i === selectedIdx));
    }} else if (e.key === 'ArrowUp') {{
        e.preventDefault();
        selectedIdx = Math.max(selectedIdx - 1, 0);
        items.forEach((item, i) => item.classList.toggle('selected', i === selectedIdx));
    }} else if (e.key === 'Tab' || e.key === 'Enter') {{
        if (selectedIdx >= 0 && items[selectedIdx]) {{
            e.preventDefault();
            searchInput.value = items[selectedIdx].dataset.value;
            suggestionsDiv.classList.add('hidden');
            filterTweets(searchInput.value);
        }}
    }} else if (e.key === 'Escape') {{
        suggestionsDiv.classList.add('hidden');
    }}
}});

document.addEventListener('click', (e) => {{
    if (!e.target.closest('.search-container')) {{
        suggestionsDiv.classList.add('hidden');
    }}
}});
</script>
"""

    # Fix nav links for index page
    index_html = HTML_BASE.format(title="Twitter Bookmarks", content=index_content)
    index_html = index_html.replace('../index.html', 'index.html')
    index_html = index_html.replace('../categories/', 'categories/')
    index_html = index_html.replace('../timeline/', 'timeline/')

    with open(MASTER_HTML_DIR / "index.html", "w", encoding="utf-8") as f:
        f.write(index_html)

    # Generate category pages
    if categories_data:
        print("Generating category pages...")
        categories = categories_data.get("categories", {})

        # Category index with timeline nav
        cat_index_content = "<h1>Categories</h1>\n"
        for cat_id, cat_info in sorted(categories.items(), key=lambda x: len(x[1].get("tweet_ids", [])), reverse=True):
            tweet_count = len(cat_info.get("tweet_ids", []))

            # Build timeline nav for this category
            timeline_html = ""
            if cat_id in category_timeline:
                years_data = category_timeline[cat_id]
                sorted_years = sorted(years_data.keys(), reverse=True)
                if sorted_years:
                    year_links = []
                    for year in sorted_years:
                        year_total = sum(years_data[year].values())
                        year_links.append(f'<span class="year-link" data-year="{year}" data-cat="{cat_id}">{year} ({year_total})</span>')
                    timeline_html = f'''
    <div class="timeline-nav" data-timeline='{json.dumps(years_data)}'>
        <div class="year-row">{" ".join(year_links)}</div>
        <div class="month-row hidden"></div>
    </div>'''

            cat_index_content += f"""
<div class="tweet-card category-card" data-cat="{cat_id}">
    <h3><a href="{cat_id}.html">{cat_info.get('name', cat_id)}</a></h3>
    <p>{cat_info.get('description', '')}</p>
    <p class="meta">{tweet_count} bookmarks</p>{timeline_html}
</div>
"""

        # Build stories availability map for JavaScript
        stories_available = {}
        if MASTER_STORIES.exists():
            stories_data = load_stories()
            for cat, years in stories_data.get("category_years", {}).items():
                stories_available[cat] = list(years.keys())

        # Add JavaScript for timeline expand/collapse
        timeline_js = f"""
<script>
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const STORIES_AVAILABLE = {json.dumps(stories_available)};

document.querySelectorAll('.year-link').forEach(link => {{
    link.addEventListener('click', function() {{
        const card = this.closest('.category-card');
        const nav = this.closest('.timeline-nav');
        const timeline = JSON.parse(nav.dataset.timeline);
        const year = this.dataset.year;
        const cat = this.dataset.cat;
        const monthRow = nav.querySelector('.month-row');

        // Toggle active state
        const wasActive = this.classList.contains('active');
        nav.querySelectorAll('.year-link').forEach(l => l.classList.remove('active'));

        if (wasActive) {{
            monthRow.classList.add('hidden');
            monthRow.innerHTML = '';
        }} else {{
            this.classList.add('active');
            const months = timeline[year] || {{}};
            const monthLinks = [];

            // Add story link if available
            if (STORIES_AVAILABLE[cat] && STORIES_AVAILABLE[cat].includes(year)) {{
                monthLinks.push(`<a href="../stories/${{cat}}/${{year}}.html" class="month-link" style="background: var(--link); color: white;">View ${{year}} Story</a>`);
            }}

            for (let m = 1; m <= 12; m++) {{
                const mm = m.toString().padStart(2, '0');
                const count = months[mm] || 0;
                if (count > 0) {{
                    monthLinks.push(`<a href="${{cat}}.html?year=${{year}}&month=${{mm}}" class="month-link">${{MONTH_NAMES[m-1]}} (${{count}})</a>`);
                }}
            }}
            monthRow.innerHTML = monthLinks.join('');
            monthRow.classList.remove('hidden');
        }}
    }});
}});
</script>
"""
        cat_index_content += timeline_js
        cat_index_html = HTML_BASE.format(title="Categories", content=cat_index_content)
        cat_index_html = cat_index_html.replace('../index.html', '../index.html')
        with open(MASTER_HTML_DIR / "categories" / "index.html", "w", encoding="utf-8") as f:
            f.write(cat_index_html)

        # Individual category pages
        for cat_id, cat_info in categories.items():
            tweet_ids = cat_info.get("tweet_ids", [])
            cat_tweets = [tweet_lookup.get(tid) for tid in tweet_ids if tid in tweet_lookup]
            cat_tweets = [t for t in cat_tweets if t]

            # Get summary
            summaries = cat_info.get("summaries", {})
            summary_html = ""
            if summaries:
                # Show most recent summary
                sorted_periods = sorted(summaries.keys(), reverse=True)
                if sorted_periods:
                    summary_html = f'<div class="summary">{summaries[sorted_periods[0]]}</div>'

            # Build year/month filter bar for category page
            cat_timeline = category_timeline.get(cat_id, {})
            filter_html = ""
            if cat_timeline:
                sorted_years = sorted(cat_timeline.keys(), reverse=True)
                year_btns = []
                for year in sorted_years:
                    year_total = sum(cat_timeline[year].values())
                    year_btns.append(f'<button class="filter-btn year-btn" data-year="{year}">{year} ({year_total})</button>')
                filter_html = f'''
<div class="filter-bar">
    <button class="filter-btn active" data-year="all">All ({len(cat_tweets)})</button>
    {" ".join(year_btns)}
</div>
<div class="month-filter hidden"></div>
'''

            cat_content = f"""
<h1>{cat_info.get('name', cat_id)}</h1>
<p class="meta"><span id="visible-count">{len(cat_tweets)}</span> bookmarks</p>
{filter_html}
{summary_html}
<div id="tweets-container">
{"".join(render_tweet_card(t, categories_data) for t in cat_tweets)}
</div>
<script>
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const catTimeline = {json.dumps(cat_timeline)};

// Parse URL params on load
const params = new URLSearchParams(window.location.search);
const filterYear = params.get('year');
const filterMonth = params.get('month');

function filterTweets(year, month) {{
    let visibleCount = 0;
    document.querySelectorAll('.tweet-card').forEach(card => {{
        const dateSpan = card.querySelector('.tweet-stats span:last-child');
        if (!dateSpan) return;
        const dateMatch = dateSpan.textContent.match(/([A-Z][a-z]+) (\\d+), (\\d+)/);
        if (!dateMatch) return;

        const tweetMonth = MONTH_NAMES.indexOf(dateMatch[1]) + 1;
        const tweetYear = dateMatch[3];
        const mm = tweetMonth.toString().padStart(2, '0');

        let show = true;
        if (year && year !== 'all') {{
            show = tweetYear === year;
            if (show && month) {{
                show = mm === month;
            }}
        }}
        card.classList.toggle('hidden', !show);
        if (show) visibleCount++;
    }});
    document.getElementById('visible-count').textContent = visibleCount;
}}

// Setup filter buttons
document.querySelectorAll('.year-btn').forEach(btn => {{
    btn.addEventListener('click', function() {{
        const year = this.dataset.year;
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        this.classList.add('active');

        // Show month filter if year selected
        const monthFilter = document.querySelector('.month-filter');
        if (year !== 'all' && catTimeline[year]) {{
            const months = catTimeline[year];
            const monthBtns = ['<button class="filter-btn month-btn active" data-month="">All months</button>'];
            for (let m = 1; m <= 12; m++) {{
                const mm = m.toString().padStart(2, '0');
                if (months[mm]) {{
                    monthBtns.push(`<button class="filter-btn month-btn" data-month="${{mm}}">${{MONTH_NAMES[m-1]}} (${{months[mm]}})</button>`);
                }}
            }}
            monthFilter.innerHTML = monthBtns.join('');
            monthFilter.classList.remove('hidden');

            // Attach month btn handlers
            monthFilter.querySelectorAll('.month-btn').forEach(mbtn => {{
                mbtn.addEventListener('click', function() {{
                    monthFilter.querySelectorAll('.month-btn').forEach(b => b.classList.remove('active'));
                    this.classList.add('active');
                    filterTweets(year, this.dataset.month);
                }});
            }});
        }} else {{
            monthFilter.classList.add('hidden');
        }}
        filterTweets(year, '');
    }});
}});

// All button handler
document.querySelector('.filter-btn[data-year="all"]')?.addEventListener('click', function() {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    this.classList.add('active');
    document.querySelector('.month-filter')?.classList.add('hidden');
    filterTweets('all', '');
}});

// Apply initial filter from URL
if (filterYear) {{
    const yearBtn = document.querySelector(`.year-btn[data-year="${{filterYear}}"]`);
    if (yearBtn) {{
        yearBtn.click();
        if (filterMonth) {{
            setTimeout(() => {{
                const monthBtn = document.querySelector(`.month-btn[data-month="${{filterMonth}}"]`);
                if (monthBtn) monthBtn.click();
            }}, 100);
        }}
    }}
}}
</script>
"""

            cat_html = HTML_BASE.format(title=cat_info.get('name', cat_id), content=cat_content)
            with open(MASTER_HTML_DIR / "categories" / f"{cat_id}.html", "w", encoding="utf-8") as f:
                f.write(cat_html)

    # Generate timeline pages
    print("Generating timeline pages...")
    by_period: dict[str, list[dict]] = defaultdict(list)

    for bookmark in bookmarks:
        dt = parse_tweet_date(bookmark.get("Created At", ""))
        if dt:
            periods = get_time_periods(dt)
            by_period[f"year-{periods['year']}"].append(bookmark)
            by_period[f"month-{periods['month']}"].append(bookmark)
            by_period[f"day-{periods['day']}"].append(bookmark)

    # Timeline index (years)
    years = sorted(set(p.split("-")[1] for p in by_period.keys() if p.startswith("year-")), reverse=True)
    timeline_index = "<h1>Timeline</h1>\n"
    for year in years:
        count = len(by_period.get(f"year-{year}", []))
        timeline_index += f'<div class="tweet-card"><a href="{year}/index.html">{year}</a> - {count} bookmarks</div>\n'

    timeline_html = HTML_BASE.format(title="Timeline", content=timeline_index)
    timeline_html = timeline_html.replace('../index.html', '../index.html')
    with open(MASTER_HTML_DIR / "timeline" / "index.html", "w", encoding="utf-8") as f:
        f.write(timeline_html)

    # Year and month pages
    for year in years:
        year_dir = MASTER_HTML_DIR / "timeline" / year
        year_dir.mkdir(exist_ok=True)

        year_tweets = by_period.get(f"year-{year}", [])
        months = sorted(set(
            p.split("-")[1] + "-" + p.split("-")[2]
            for p in by_period.keys()
            if p.startswith(f"month-{year}-")
        ), reverse=True)

        year_content = f"<h1>{year}</h1>\n<p class='meta'>{len(year_tweets)} bookmarks</p>\n"
        for month in months:
            month_count = len(by_period.get(f"month-{month}", []))
            month_name = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
            month_dir = month.split("-")[1]
            year_content += f'<div class="tweet-card"><a href="{month_dir}/index.html">{month_name}</a> - {month_count} bookmarks</div>\n'

        year_html = HTML_BASE.format(title=year, content=year_content)
        with open(year_dir / "index.html", "w", encoding="utf-8") as f:
            f.write(year_html)

        # Month pages
        for month in months:
            month_num = month.split("-")[1]
            month_dir = year_dir / month_num
            month_dir.mkdir(exist_ok=True)

            month_tweets = by_period.get(f"month-{month}", [])
            month_name = datetime.strptime(month, "%Y-%m").strftime("%B %Y")

            month_content = f"<h1>{month_name}</h1>\n<p class='meta'>{len(month_tweets)} bookmarks</p>\n"
            month_content += "\n".join(render_tweet_card(t, categories_data) for t in month_tweets)

            # Fix relative paths for deeper nesting
            month_html = HTML_BASE.format(title=month_name, content=month_content)
            month_html = month_html.replace('../index.html', '../../../index.html')
            month_html = month_html.replace('../categories/', '../../../categories/')
            month_html = month_html.replace('../timeline/', '../../../timeline/')
            month_html = month_html.replace('../tweets/', '../../../tweets/')
            month_html = month_html.replace('../../media/', '../../../../media/')

            with open(month_dir / "index.html", "w", encoding="utf-8") as f:
                f.write(month_html)

    # Generate story pages if stories.json exists
    if MASTER_STORIES.exists():
        print("Generating story pages...")
        stories_data = load_stories()
        generate_story_pages(bookmarks, categories_data, stories_data)

    print(f"\nGenerated HTML pages in {MASTER_HTML_DIR}")
    print(f"Open {MASTER_HTML_DIR / 'index.html'} in a browser to view")


def cmd_export(args: argparse.Namespace) -> None:
    """Export for NotebookLM"""
    print("=== Exporting for NotebookLM ===")

    if not MASTER_JSON.exists():
        print(f"Master JSON not found. Run 'merge' first.")
        return

    with open(MASTER_JSON, "r", encoding="utf-8") as f:
        bookmarks = json.load(f)

    # Load categories if available
    categories_data = None
    if MASTER_CATEGORIES.exists():
        with open(MASTER_CATEGORIES, "r", encoding="utf-8") as f:
            categories_data = json.load(f)

    # Ensure export directory exists
    MASTER_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (MASTER_EXPORTS_DIR / "by_category").mkdir(exist_ok=True)

    # Format a bookmark for NotebookLM
    def format_bookmark(b: dict) -> str:
        date = b.get("Created At", "Unknown date")
        author = f"@{b.get('User Screen Name', 'unknown')} ({b.get('User Name', '')})"
        text = b.get("Full Text", "")
        stats = f"Likes: {b.get('Favorite Count', 0)}, Retweets: {b.get('Retweet Count', 0)}"

        categories = ""
        if categories_data:
            tweet_cats = categories_data.get("tweet_categories", {}).get(b.get("Tweet Id", ""), [])
            if tweet_cats:
                cat_names = [categories_data.get("categories", {}).get(c, {}).get("name", c) for c in tweet_cats]
                categories = f"\nCategories: {', '.join(cat_names)}"

        return f"""
---
Author: {author}
Date: {date}
{stats}{categories}

{text}
"""

    # Export all bookmarks
    print("Exporting all bookmarks...")
    all_text = "# Twitter Bookmarks Export\n\n"
    all_text += f"Total bookmarks: {len(bookmarks)}\n"
    all_text += f"Export date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

    for b in bookmarks:
        all_text += format_bookmark(b)

    with open(MASTER_EXPORTS_DIR / "all_bookmarks.txt", "w", encoding="utf-8") as f:
        f.write(all_text)

    # Export by category
    if categories_data:
        print("Exporting by category...")
        tweet_lookup = {b["Tweet Id"]: b for b in bookmarks}

        for cat_id, cat_info in categories_data.get("categories", {}).items():
            tweet_ids = cat_info.get("tweet_ids", [])
            if not tweet_ids:
                continue

            cat_text = f"# {cat_info.get('name', cat_id)}\n\n"
            cat_text += f"{cat_info.get('description', '')}\n"
            cat_text += f"Bookmarks: {len(tweet_ids)}\n\n"

            # Add summaries
            for period, summary in sorted(cat_info.get("summaries", {}).items(), reverse=True):
                cat_text += f"## {period} Summary\n{summary}\n\n"

            cat_text += "## Bookmarks\n"
            for tid in tweet_ids:
                if tid in tweet_lookup:
                    cat_text += format_bookmark(tweet_lookup[tid])

            with open(MASTER_EXPORTS_DIR / "by_category" / f"{cat_id}.txt", "w", encoding="utf-8") as f:
                f.write(cat_text)

    print(f"\nExported to {MASTER_EXPORTS_DIR}")


def cmd_clean(args: argparse.Namespace) -> None:
    """Delete generated files (master/) to allow re-running"""
    print("=== Clean generated files ===")

    if not MASTER_DIR.exists():
        print("Master directory not found. Nothing to clean.")
        return

    # Count what will be deleted
    file_count = sum(1 for _ in MASTER_DIR.rglob("*") if _.is_file())

    print(f"This will delete {file_count} generated files in {MASTER_DIR}")
    print("Raw data in raw/ will NOT be affected.")

    confirm = input("\nAre you sure? Type 'yes' to confirm: ")
    if confirm.lower() != "yes":
        print("Cancelled.")
        return

    shutil.rmtree(MASTER_DIR)
    MASTER_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Cleaned {MASTER_DIR}")


def cmd_cleanup_raw(args: argparse.Namespace) -> None:
    """Delete raw exports after QA (DESTRUCTIVE - removes original data)"""
    print("=== Cleanup raw data ===")

    if not RAW_DIR.exists():
        print("Raw directory not found. Nothing to clean up.")
        return

    # Count files
    json_count = len(list(RAW_JSON_DIR.glob("*.json"))) if RAW_JSON_DIR.exists() else 0
    media_dirs = len([d for d in RAW_MEDIA_DIR.iterdir() if d.is_dir()]) if RAW_MEDIA_DIR.exists() else 0

    print(f"WARNING: This will PERMANENTLY delete original export data:")
    print(f"  - {json_count} JSON files in {RAW_JSON_DIR}")
    print(f"  - {media_dirs} media export directories in {RAW_MEDIA_DIR}")
    print("\nOnly do this after verifying master/ contains all your data!")

    confirm = input("\nType 'DELETE' to confirm: ")
    if confirm != "DELETE":
        print("Cancelled.")
        return

    shutil.rmtree(RAW_DIR)
    print(f"Deleted {RAW_DIR}")


def cmd_update(args: argparse.Namespace) -> None:
    """Incremental update: merge new, categorize new only, regenerate HTML"""
    print("=== Incremental Update ===")

    # Step 1: Load existing data
    existing_ids: set[str] = set()
    existing_categories: dict = {"categories": {}, "tweet_categories": {}}

    if MASTER_JSON.exists():
        with open(MASTER_JSON, "r", encoding="utf-8") as f:
            existing_bookmarks = json.load(f)
            existing_ids = {b["Tweet Id"] for b in existing_bookmarks}
        print(f"Existing bookmarks: {len(existing_ids)}")

    if MASTER_CATEGORIES.exists():
        with open(MASTER_CATEGORIES, "r", encoding="utf-8") as f:
            existing_categories = json.load(f)
        print(f"Existing categories: {len(existing_categories.get('categories', {}))}")

    # Step 2: Merge new JSON files
    print("\n--- Merging new bookmarks ---")
    all_bookmarks = load_all_json_files()
    if not all_bookmarks:
        print("No new JSON files found.")
        return

    deduped = deduplicate_bookmarks(all_bookmarks)
    new_ids = {b["Tweet Id"] for b in deduped} - existing_ids
    print(f"New bookmarks to process: {len(new_ids)}")

    # Sort and save merged bookmarks - parse actual date, not string sort
    from datetime import timezone
    deduped.sort(key=lambda x: parse_tweet_date(x.get("Created At", "")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    MASTER_DIR.mkdir(parents=True, exist_ok=True)
    with open(MASTER_JSON, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(deduped)} total bookmarks to {MASTER_JSON}")

    # Step 3: Consolidate new media
    print("\n--- Consolidating media ---")
    cmd_consolidate(args)

    # Step 4: Categorize only NEW tweets
    if new_ids:
        print(f"\n--- Categorizing {len(new_ids)} new bookmarks ---")

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("Warning: ANTHROPIC_API_KEY not set. Skipping categorization.")
            print("Set it with: export ANTHROPIC_API_KEY='your-key-here'")
        else:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)

                # Get new bookmarks
                new_bookmarks = [b for b in deduped if b["Tweet Id"] in new_ids]

                # Get existing category list for context
                existing_cat_info = existing_categories.get("categories", {})
                existing_cat_list = ", ".join(existing_cat_info.keys()) if existing_cat_info else ""

                # Phase 1: Check if we need new categories (sample new tweets)
                sample_size = min(50, len(new_bookmarks))
                sample_texts = [b.get("Full Text", "")[:300] for b in new_bookmarks[:sample_size]]

                if existing_cat_list:
                    taxonomy_prompt = f"""Here are existing categories: {existing_cat_list}

Analyze these {sample_size} NEW Twitter bookmarks. Determine if any new categories are needed.

Return JSON with ONLY new categories (if any). Use kebab-case IDs:
{{
  "new_categories": {{
    "category-id": {{
      "name": "Human Readable Name",
      "description": "Brief description"
    }}
  }}
}}

If no new categories needed, return: {{"new_categories": {{}}}}

New tweets:
{chr(10).join(f'- {t[:150]}...' for t in sample_texts[:20])}
"""
                else:
                    taxonomy_prompt = f"""Analyze these {sample_size} Twitter bookmarks and create a category taxonomy.

Create 10-20 categories. Use kebab-case for IDs:
{{
  "new_categories": {{
    "category-id": {{
      "name": "Human Readable Name",
      "description": "Brief description"
    }}
  }}
}}

Tweets:
{chr(10).join(f'- {t[:150]}...' for t in sample_texts[:20])}
"""

                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=2000,
                    messages=[{"role": "user", "content": taxonomy_prompt}]
                )

                try:
                    taxonomy_text = response.content[0].text
                    if "```json" in taxonomy_text:
                        taxonomy_text = taxonomy_text.split("```json")[1].split("```")[0]
                    elif "```" in taxonomy_text:
                        taxonomy_text = taxonomy_text.split("```")[1].split("```")[0]
                    taxonomy = json.loads(taxonomy_text)
                    new_categories = taxonomy.get("new_categories", {})

                    if new_categories:
                        print(f"Discovered {len(new_categories)} new categories:")
                        for cat_id, cat_info in new_categories.items():
                            print(f"  + {cat_id}: {cat_info.get('name', cat_id)}")
                            existing_cat_info[cat_id] = cat_info
                except (json.JSONDecodeError, IndexError) as e:
                    print(f"Warning: Error parsing taxonomy: {e}")
                    new_categories = {}

                # Phase 2: Categorize new tweets
                all_cat_list = ", ".join(existing_cat_info.keys())
                tweet_categories = dict(existing_categories.get("tweet_categories", {}))
                category_tweets: dict[str, list[str]] = defaultdict(list)

                # Rebuild category_tweets from existing data
                for cat_id, cat_info in existing_cat_info.items():
                    if "tweet_ids" in cat_info:
                        category_tweets[cat_id] = list(cat_info.get("tweet_ids", []))

                batch_size = 20
                for i in range(0, len(new_bookmarks), batch_size):
                    batch = new_bookmarks[i:i + batch_size]
                    print(f"Categorizing batch {i // batch_size + 1}/{(len(new_bookmarks) + batch_size - 1) // batch_size}...")

                    batch_prompt = f"""Categorize these tweets. Available categories: {all_cat_list}

Assign 1-3 categories to each tweet. Return JSON only:
{{"tweet_id": ["category1", "category2"]}}

Tweets:
"""
                    for b in batch:
                        batch_prompt += f'\n{b.get("Tweet Id")}: {b.get("Full Text", "")[:300]}'

                    response = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=2000,
                        messages=[{"role": "user", "content": batch_prompt}]
                    )

                    try:
                        result_text = response.content[0].text
                        if "```json" in result_text:
                            result_text = result_text.split("```json")[1].split("```")[0]
                        elif "```" in result_text:
                            result_text = result_text.split("```")[1].split("```")[0]
                        batch_results = json.loads(result_text)

                        for tweet_id, cats in batch_results.items():
                            tweet_categories[tweet_id] = cats
                            for cat in cats:
                                if cat in existing_cat_info and tweet_id not in category_tweets[cat]:
                                    category_tweets[cat].append(tweet_id)
                    except (json.JSONDecodeError, IndexError) as e:
                        print(f"  Warning: Error parsing batch: {e}")

                # Build updated categories structure
                final_categories = {
                    "categories": {},
                    "tweet_categories": tweet_categories
                }

                for cat_id, cat_info in existing_cat_info.items():
                    final_categories["categories"][cat_id] = {
                        "name": cat_info.get("name", cat_id),
                        "description": cat_info.get("description", ""),
                        "tweet_ids": category_tweets.get(cat_id, []),
                        "summaries": existing_categories.get("categories", {}).get(cat_id, {}).get("summaries", {})
                    }

                with open(MASTER_CATEGORIES, "w", encoding="utf-8") as f:
                    json.dump(final_categories, f, indent=2, ensure_ascii=False)

                print(f"Updated categories: {len(tweet_categories)} tweets categorized")

            except ImportError:
                print("Warning: anthropic package not installed. Skipping categorization.")
    else:
        print("\nNo new bookmarks to categorize.")

    # Step 5: Regenerate HTML
    print("\n--- Regenerating HTML ---")
    cmd_generate(args)

    # Step 6: Export
    print("\n--- Exporting ---")
    cmd_export(args)

    print("\n=== Update complete ===")


def cmd_stories(args: argparse.Namespace) -> None:
    """Generate AI stories for category/year combinations"""

    # Handle --list-categories
    if getattr(args, 'list_categories', False):
        if not MASTER_CATEGORIES.exists():
            print("Categories not found. Run 'categorize' first.")
            return
        with open(MASTER_CATEGORIES, "r", encoding="utf-8") as f:
            categories_data = json.load(f)
        print("Available categories:\n")
        for cat_id, cat_info in sorted(categories_data.get("categories", {}).items()):
            tweet_count = len(cat_info.get("tweet_ids", []))
            print(f"  {cat_id}")
            print(f"    Name: {cat_info.get('name', cat_id)}")
            print(f"    Tweets: {tweet_count}\n")
        return

    print("=== Generating Stories ===")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        return

    if not MASTER_JSON.exists():
        print("Master JSON not found. Run 'merge' first.")
        return

    if not MASTER_CATEGORIES.exists():
        print("Categories not found. Run 'categorize' first.")
        return

    # Load data
    with open(MASTER_JSON, "r", encoding="utf-8") as f:
        bookmarks = json.load(f)

    with open(MASTER_CATEGORIES, "r", encoding="utf-8") as f:
        categories_data = json.load(f)

    stories_data = load_stories()

    print(f"Loaded {len(bookmarks)} bookmarks, {len(categories_data.get('categories', {}))} categories")

    try:
        import anthropic
    except ImportError:
        print("Error: anthropic package not installed")
        return

    client = anthropic.Anthropic(api_key=api_key)

    # Build category timeline to find category/year combinations
    category_timeline = build_category_timeline(bookmarks, categories_data)

    # Determine which category/years need generation
    to_generate = []
    min_tweets = getattr(args, 'min_tweets', 10)
    force_year = getattr(args, 'force_year', None)
    target_category = getattr(args, 'category', None)

    for cat_id, years in category_timeline.items():
        if target_category and cat_id != target_category:
            continue

        for year, months in years.items():
            tweet_count = sum(months.values())
            if tweet_count < min_tweets:
                continue

            # Get tweet IDs for this category/year
            tweets = get_category_year_tweets(cat_id, year, bookmarks, categories_data)
            tweet_ids = [t["Tweet Id"] for t in tweets]

            if should_regenerate_story(stories_data, cat_id, year, tweet_ids, force_year):
                to_generate.append((cat_id, year, tweet_count))

    if not to_generate:
        print("No stories need regeneration.")
        return

    print(f"\nWill generate {len(to_generate)} stories:")
    for cat_id, year, count in to_generate:
        cat_name = categories_data.get("categories", {}).get(cat_id, {}).get("name", cat_id)
        print(f"  - {cat_name} / {year} ({count} tweets)")

    # Generate each story
    for i, (cat_id, year, tweet_count) in enumerate(to_generate, 1):
        cat_name = categories_data.get("categories", {}).get(cat_id, {}).get("name", cat_id)
        print(f"\n[{i}/{len(to_generate)}] Generating story: {cat_name} / {year}")
        generate_story(client, stories_data, cat_id, year, bookmarks, categories_data)

    # Save stories data
    save_stories(stories_data)
    print(f"\nStories saved to {MASTER_STORIES}")
    print("Run 'generate' to create HTML pages.")


def cmd_all(args: argparse.Namespace) -> None:
    """Run merge, consolidate, generate, and export"""
    cmd_merge(args)
    print()
    cmd_consolidate(args)
    print()
    cmd_generate(args)
    print()
    cmd_export(args)


# ==================== Publish Commands ====================

GITHUB_PAGES_REPO = "b3rntsen/b3rntsen.github.io"
PUBLISH_SUBDIR = "twitter"


def fix_paths_for_publish(html: str, depth: int = 0) -> str:
    """Fix relative paths for published version at /twitter/

    depth=0: page at /twitter/index.html
    depth=1: page at /twitter/categories/index.html
    depth=2: page at /twitter/stories/cat/year.html
    """
    # Navigation paths in HTML_BASE use ../
    # We need to adjust based on page depth

    if depth == 0:
        # Root level: /twitter/index.html
        # ../index.html -> index.html (self)
        # ../categories/ -> categories/
        # ../timeline/ -> timeline/
        # ../stories/ -> stories/
        # ../tweets/ -> tweets/
        html = html.replace('href="../index.html"', 'href="index.html"')
        html = html.replace('href="../categories/', 'href="categories/')
        html = html.replace('href="../timeline/', 'href="timeline/')
        html = html.replace('href="../stories/', 'href="stories/')
        html = html.replace('href="../tweets/', 'href="tweets/')
    elif depth == 1:
        # One level deep: /twitter/categories/index.html
        # Paths are already correct (../ goes to /twitter/)
        pass
    elif depth == 2:
        # Two levels deep: /twitter/stories/cat/year.html
        # Need to go up two levels to /twitter/
        html = html.replace('href="../index.html"', 'href="../../index.html"')
        html = html.replace('href="../categories/', 'href="../../categories/')
        html = html.replace('href="../timeline/', 'href="../../timeline/')
        html = html.replace('href="../stories/', 'href="../../stories/')
        html = html.replace('href="../tweets/', 'href="../../tweets/')

    return html


def generate_html_cdn(output_dir: Path, bookmarks: list[dict], categories_data: dict,
                      stories_data: dict) -> None:
    """Generate HTML pages using Twitter CDN for media (no local media needed)"""
    import tempfile

    html_dir = output_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    (html_dir / "categories").mkdir(exist_ok=True)
    (html_dir / "timeline").mkdir(exist_ok=True)
    (html_dir / "tweets").mkdir(exist_ok=True)
    (html_dir / "stories").mkdir(exist_ok=True)

    tweet_lookup = {b["Tweet Id"]: b for b in bookmarks}
    timeline_data = build_category_timeline(bookmarks, categories_data)

    # Build search index (not used for CDN version, but function prints progress)
    print("Building search index...")
    _ = build_search_index(bookmarks)

    # Generate main index (chronological)
    print("Generating main index...")
    sorted_bookmarks = sorted(
        bookmarks,
        key=lambda x: parse_tweet_date(x.get("Created At", "")) or datetime.min.replace(tzinfo=None),
        reverse=True
    )
    tweets_html = "\n".join(render_tweet_card(b, categories_data, use_cdn=True) for b in sorted_bookmarks)
    # Simplified search (no autocomplete data for published version)
    content = f'''
<h1>Twitter Bookmarks</h1>
<p class="meta">{len(bookmarks)} bookmarks</p>
<div class="tweet-list">
{tweets_html}
</div>
'''
    page = HTML_BASE.format(title="Twitter Bookmarks", content=content)
    page = fix_paths_for_publish(page, depth=0)  # Root level
    with open(html_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(page)

    # Generate category index
    print("Generating category pages...")
    categories = categories_data.get("categories", {})
    cat_list_html = ""
    for cat_id, cat_info in sorted(categories.items(), key=lambda x: x[1].get("name", x[0])):
        tweet_count = len(cat_info.get("tweet_ids", []))
        cat_list_html += f'''
<div class="category-card">
    <h3><a href="{cat_id}.html">{cat_info.get("name", cat_id)}</a></h3>
    <p>{cat_info.get("description", "")[:200]}</p>
    <span class="meta">{tweet_count} bookmarks</span>
</div>
'''
    content = f'''
<h1>Categories</h1>
<div class="category-list">
{cat_list_html}
</div>
'''
    page = HTML_BASE.format(title="Categories", content=content)
    page = fix_paths_for_publish(page, depth=1)  # One level deep
    with open(html_dir / "categories" / "index.html", "w", encoding="utf-8") as f:
        f.write(page)

    # Generate individual category pages
    for cat_id, cat_info in categories.items():
        cat_tweets = [tweet_lookup[tid] for tid in cat_info.get("tweet_ids", []) if tid in tweet_lookup]
        cat_tweets.sort(
            key=lambda x: parse_tweet_date(x.get("Created At", "")) or datetime.min.replace(tzinfo=None),
            reverse=True
        )
        tweets_html = "\n".join(render_tweet_card(b, categories_data, use_cdn=True) for b in cat_tweets)
        content = f'''
<h1>{cat_info.get("name", cat_id)}</h1>
<p class="meta">{len(cat_tweets)} bookmarks</p>
<p>{cat_info.get("description", "")}</p>
<div class="tweet-list">
{tweets_html}
</div>
'''
        page = HTML_BASE.format(title=cat_info.get("name", cat_id), content=content)
        page = fix_paths_for_publish(page, depth=1)  # One level deep
        with open(html_dir / "categories" / f"{cat_id}.html", "w", encoding="utf-8") as f:
            f.write(page)

    # Generate stories pages if available
    if stories_data and stories_data.get("category_years"):
        print("Generating story pages...")
        generate_stories_index(stories_data, categories_data)
        # Copy stories from master to output
        src_stories = MASTER_HTML_DIR / "stories"
        if src_stories.exists():
            import shutil as sh
            dst_stories = html_dir / "stories"
            if dst_stories.exists():
                sh.rmtree(dst_stories)
            sh.copytree(src_stories, dst_stories)

            # Fix paths in copied story files
            for html_file in dst_stories.glob("**/*.html"):
                with open(html_file, "r", encoding="utf-8") as f:
                    content = f.read()

                # Determine depth based on file location
                rel_path = html_file.relative_to(dst_stories)
                depth = len(rel_path.parts)  # index.html=1, cat/year.html=2

                if depth == 1:
                    # stories/index.html
                    content = fix_paths_for_publish(content, depth=1)
                else:
                    # stories/cat/year.html
                    content = fix_paths_for_publish(content, depth=2)

                # Remove local media paths (they won't work anyway)
                # Replace with placeholder or remove media sections
                content = content.replace('../../../media/', 'https://via.placeholder.com/400x300?text=Media+Unavailable&')

                with open(html_file, "w", encoding="utf-8") as f:
                    f.write(content)

    print(f"Generated CDN-based HTML in {html_dir}")


def cmd_publish(args: argparse.Namespace) -> None:
    """Publish HTML with Twitter CDN links to GitHub Pages"""
    import subprocess
    import tempfile

    # Check for required data
    if not MASTER_JSON.exists():
        print("Error: No bookmarks found. Run 'merge' first.")
        return

    with open(MASTER_JSON, "r", encoding="utf-8") as f:
        bookmarks = json.load(f)

    categories_data = {}
    if MASTER_CATEGORIES.exists():
        with open(MASTER_CATEGORIES, "r", encoding="utf-8") as f:
            categories_data = json.load(f)

    stories_data = {}
    if MASTER_STORIES.exists():
        with open(MASTER_STORIES, "r", encoding="utf-8") as f:
            stories_data = json.load(f)

    print(f"=== Publishing to {GITHUB_PAGES_REPO}/{PUBLISH_SUBDIR} ===")

    # Create temp directory for generated content
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        gen_dir = tmpdir / "generated"

        # Generate HTML with CDN links
        print("\nGenerating HTML with Twitter CDN links...")
        generate_html_cdn(gen_dir, bookmarks, categories_data, stories_data)

        # Clone the GitHub Pages repo
        print(f"\nCloning {GITHUB_PAGES_REPO}...")
        repo_dir = tmpdir / "repo"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", f"git@github.com:{GITHUB_PAGES_REPO}.git", str(repo_dir)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"Error cloning repo: {result.stderr}")
            return

        # Remove existing twitter folder if it exists
        publish_dir = repo_dir / PUBLISH_SUBDIR
        if publish_dir.exists():
            shutil.rmtree(publish_dir)

        # Copy generated HTML to publish directory
        shutil.copytree(gen_dir / "html", publish_dir)

        # Commit and push
        print("\nCommitting and pushing...")
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)

        # Check if there are changes to commit
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            cwd=repo_dir, capture_output=True
        )
        if result.returncode == 0:
            print("No changes to publish.")
            return

        subprocess.run(
            ["git", "commit", "-m", f"Update {PUBLISH_SUBDIR} bookmarks"],
            cwd=repo_dir, check=True
        )
        subprocess.run(["git", "push"], cwd=repo_dir, check=True)

        print(f"\n✓ Published to https://dethele.com/{PUBLISH_SUBDIR}/")


def cmd_unpublish(args: argparse.Namespace) -> None:
    """Remove published content from GitHub Pages"""
    import subprocess
    import tempfile

    print(f"=== Unpublishing {PUBLISH_SUBDIR} from {GITHUB_PAGES_REPO} ===")

    confirm = input(f"This will remove {PUBLISH_SUBDIR}/ from {GITHUB_PAGES_REPO}. Type 'DELETE' to confirm: ")
    if confirm != "DELETE":
        print("Cancelled.")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Clone the repo
        print(f"\nCloning {GITHUB_PAGES_REPO}...")
        repo_dir = tmpdir / "repo"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", f"git@github.com:{GITHUB_PAGES_REPO}.git", str(repo_dir)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"Error cloning repo: {result.stderr}")
            return

        # Check if folder exists
        publish_dir = repo_dir / PUBLISH_SUBDIR
        if not publish_dir.exists():
            print(f"{PUBLISH_SUBDIR}/ does not exist in repo.")
            return

        # Remove the folder
        shutil.rmtree(publish_dir)

        # Commit and push
        print("\nCommitting and pushing...")
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Remove {PUBLISH_SUBDIR}"],
            cwd=repo_dir, check=True
        )
        subprocess.run(["git", "push"], cwd=repo_dir, check=True)

        print(f"\n✓ Unpublished {PUBLISH_SUBDIR}/ from {GITHUB_PAGES_REPO}")


def main():
    parser = argparse.ArgumentParser(
        description="Twitter Bookmarks Merger Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("merge", help="Merge and deduplicate JSON files")
    subparsers.add_parser("consolidate", help="Consolidate media files")
    subparsers.add_parser("categorize", help="Categorize bookmarks with AI")
    subparsers.add_parser("generate", help="Generate HTML pages")
    subparsers.add_parser("export", help="Export for NotebookLM")
    subparsers.add_parser("update", help="Incremental update: merge new, categorize new only, regenerate")
    subparsers.add_parser("clean", help="Delete generated files (master/) to re-run")
    subparsers.add_parser("cleanup-raw", help="Delete raw exports (DESTRUCTIVE)")
    subparsers.add_parser("all", help="Run merge, consolidate, generate, export")

    # Stories command with options
    stories_parser = subparsers.add_parser("stories", help="Generate AI stories for categories")
    stories_parser.add_argument("--list-categories", action="store_true", help="List available categories and exit")
    stories_parser.add_argument("--force-year", type=int, help="Force regenerate specific year")
    stories_parser.add_argument("--min-tweets", type=int, default=10, help="Minimum tweets for story (default: 10)")
    stories_parser.add_argument("--category", type=str, help="Generate for specific category only")

    # Publish commands
    subparsers.add_parser("publish", help="Publish to GitHub Pages (dethele.com/twitter) using Twitter CDN")
    subparsers.add_parser("unpublish", help="Remove from GitHub Pages (DESTRUCTIVE)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "merge": cmd_merge,
        "consolidate": cmd_consolidate,
        "categorize": cmd_categorize,
        "generate": cmd_generate,
        "export": cmd_export,
        "update": cmd_update,
        "clean": cmd_clean,
        "cleanup-raw": cmd_cleanup_raw,
        "all": cmd_all,
        "stories": cmd_stories,
        "publish": cmd_publish,
        "unpublish": cmd_unpublish,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
