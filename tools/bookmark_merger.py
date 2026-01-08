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
import subprocess
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
MASTER_AUTHORS = MASTER_DIR / "authors.json"
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

    # Generate video thumbnails
    print("\nGenerating video thumbnails...")
    thumb_count = generate_video_thumbnails(MASTER_MEDIA_DIR)
    if thumb_count > 0:
        print(f"  Generated {thumb_count} new thumbnails")
    else:
        print("  No new thumbnails needed")


def generate_video_thumbnails(media_dir: Path) -> int:
    """Generate thumbnails for all videos in media directory using ffmpeg.

    Creates thumb_{video_stem}.jpg next to each video file.
    Skips if thumbnail already exists. Requires ffmpeg to be installed.
    """
    VIDEO_EXTENSIONS = [".mp4", ".webm", ".mov"]
    count = 0
    errors = 0

    for tweet_dir in media_dir.iterdir():
        if not tweet_dir.is_dir():
            continue

        for video_file in tweet_dir.iterdir():
            if video_file.suffix.lower() not in VIDEO_EXTENSIONS:
                continue

            thumb_path = tweet_dir / f"thumb_{video_file.stem}.jpg"
            if thumb_path.exists():
                continue  # Already generated

            try:
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-i", str(video_file),
                        "-ss", "00:00:01",  # 1 second into video
                        "-vframes", "1",     # Single frame
                        "-q:v", "2",         # Quality (2 = high)
                        str(thumb_path),
                        "-y",                # Overwrite if exists
                        "-loglevel", "error" # Suppress output
                    ],
                    capture_output=True,
                    check=True
                )
                count += 1
            except FileNotFoundError:
                # ffmpeg not installed - warn once and continue
                if errors == 0:
                    print("  Warning: ffmpeg not found. Install with: brew install ffmpeg")
                errors += 1
            except subprocess.CalledProcessError as e:
                # ffmpeg failed for this video
                if errors < 5:
                    print(f"  Warning: Could not generate thumbnail for {video_file.name}")
                errors += 1

    return count


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


# ==================== Author Helpers ====================

def build_author_profiles(bookmarks: list[dict]) -> dict:
    """Extract unique authors with their stats and tweet IDs from bookmarks"""
    authors = {}
    for bookmark in bookmarks:
        screen_name = bookmark.get("User Screen Name", "")
        if not screen_name:
            continue

        screen_name_lower = screen_name.lower()
        if screen_name_lower not in authors:
            authors[screen_name_lower] = {
                "name": bookmark.get("User Name", ""),
                "screen_name": bookmark.get("User Screen Name", ""),
                "avatar": bookmark.get("User Avatar Url", ""),
                "description": bookmark.get("User Description", ""),
                "location": bookmark.get("User Location", ""),
                "followers": int(bookmark.get("User Followers Count", 0) or 0),
                "verified": bookmark.get("User Is Blue Verified", "") == "Yes",
                "tweet_ids": [],
                "bookmark_count": 0,
                "category": None,
                "category_confidence": None,
                "summary": None
            }
        authors[screen_name_lower]["tweet_ids"].append(bookmark.get("Tweet Id", ""))
        authors[screen_name_lower]["bookmark_count"] += 1
        # Update followers count if newer bookmark has higher count
        new_followers = int(bookmark.get("User Followers Count", 0) or 0)
        if new_followers > authors[screen_name_lower]["followers"]:
            authors[screen_name_lower]["followers"] = new_followers
            # Also update other profile info with the latest
            authors[screen_name_lower]["name"] = bookmark.get("User Name", "")
            authors[screen_name_lower]["avatar"] = bookmark.get("User Avatar Url", "")
            authors[screen_name_lower]["description"] = bookmark.get("User Description", "")
            authors[screen_name_lower]["location"] = bookmark.get("User Location", "")
            authors[screen_name_lower]["verified"] = bookmark.get("User Is Blue Verified", "") == "Yes"

    return authors


def load_authors() -> dict:
    """Load existing authors data or return empty structure"""
    if MASTER_AUTHORS.exists():
        with open(MASTER_AUTHORS, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"generated_at": None, "author_categories": {}, "authors": {}}


def save_authors(authors_data: dict) -> None:
    """Save authors data to JSON"""
    authors_data["generated_at"] = datetime.now().isoformat()
    with open(MASTER_AUTHORS, "w", encoding="utf-8") as f:
        json.dump(authors_data, f, indent=2, ensure_ascii=False)


def categorize_authors_ai(client, authors: dict, bookmarks: list[dict], min_bookmarks: int = 3) -> dict:
    """Use AI to categorize authors into profile types.

    Only categorizes authors with at least min_bookmarks bookmarks.
    Returns updated authors dict with category, confidence, and summary.
    """
    # Build tweet lookup for getting sample tweets
    tweet_lookup = {b["Tweet Id"]: b for b in bookmarks}

    # Filter to authors with enough bookmarks
    to_categorize = {k: v for k, v in authors.items() if v["bookmark_count"] >= min_bookmarks}
    print(f"Authors with {min_bookmarks}+ bookmarks: {len(to_categorize)} (of {len(authors)} total)")

    if not to_categorize:
        return authors

    # Phase 1: Discover/confirm author categories from top authors
    print("\nPhase 1: Confirming author category taxonomy...")
    top_authors = sorted(to_categorize.values(), key=lambda x: x["bookmark_count"], reverse=True)[:50]

    author_samples = []
    for author in top_authors:
        sample_tweets = []
        for tid in author["tweet_ids"][:3]:
            if tid in tweet_lookup:
                sample_tweets.append(tweet_lookup[tid].get("Full Text", "")[:150])
        author_samples.append(
            f"@{author['screen_name']} ({author['followers']} followers, {author['bookmark_count']} bookmarks)\n"
            f"  Bio: {author['description'][:200] if author['description'] else 'N/A'}\n"
            f"  Tweets: {'; '.join(sample_tweets)}"
        )

    taxonomy_prompt = f"""Analyze these Twitter/X authors from someone's bookmarks and create a category taxonomy.

The categories should help classify author TYPES based on how they use the platform. Use these seed concepts:
- Scientist/Academic - Researchers, professors, domain experts with credentials
- Author/Creator - Writers, documentary makers, podcast hosts, focused on specific topics
- Marketer/Promoter - Revenue-driven, hooks, "follow me for more", newsletter pushers
- Influencer/Celebrity - Media personalities, product placements, personal brand focus
- Journalist/Reporter - News coverage, investigative work, media outlets
- Builder/Founder - Entrepreneurs, startup founders, shipping products
- Analyst/Commentator - Opinions, takes, commentary on current events
- Educator/Explainer - Thread writers, explainers, teaching complex topics
- Curator/Aggregator - Sharing others' content, reposting, curation focus

Feel free to adjust/merge/rename these categories based on the actual authors.

Return JSON only, no other text:
{{
  "categories": {{
    "category-id": {{
      "name": "Human Readable Name",
      "description": "Brief description of what this type of author does"
    }}
  }}
}}

AUTHORS:
{chr(10).join(author_samples)}
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
        author_categories = taxonomy.get("categories", {})
    except (json.JSONDecodeError, IndexError) as e:
        print(f"Error parsing taxonomy: {e}")
        print(f"Response: {response.content[0].text[:500]}")
        # Use default categories
        author_categories = {
            "scientist-academic": {"name": "Scientist/Academic", "description": "Researchers, professors, domain experts"},
            "author-creator": {"name": "Author/Creator", "description": "Writers, documentary makers, podcast hosts"},
            "marketer-promoter": {"name": "Marketer/Promoter", "description": "Revenue-driven, promotional content"},
            "influencer-celebrity": {"name": "Influencer/Celebrity", "description": "Media personalities, personal brands"},
            "journalist-reporter": {"name": "Journalist/Reporter", "description": "News coverage, investigative work"},
            "builder-founder": {"name": "Builder/Founder", "description": "Entrepreneurs, startup founders"},
            "analyst-commentator": {"name": "Analyst/Commentator", "description": "Opinions, commentary on events"},
            "educator-explainer": {"name": "Educator/Explainer", "description": "Thread writers, teaching complex topics"},
            "curator-aggregator": {"name": "Curator/Aggregator", "description": "Sharing others' content, curation"}
        }

    print(f"Using {len(author_categories)} author categories:")
    for cat_id, cat_info in author_categories.items():
        print(f"  - {cat_id}: {cat_info.get('name', cat_id)}")

    # Phase 2: Categorize authors in batches
    print("\nPhase 2: Categorizing authors...")
    category_list = ", ".join(author_categories.keys())
    authors_list = list(to_categorize.items())
    batch_size = 20

    for i in range(0, len(authors_list), batch_size):
        batch = authors_list[i:i + batch_size]
        print(f"Processing batch {i // batch_size + 1}/{(len(authors_list) + batch_size - 1) // batch_size}...")

        batch_prompt = f"""Categorize these Twitter/X authors. Available categories: {category_list}

For each author, provide:
1. category: The best-fit category ID
2. confidence: "high", "medium", or "low"
3. summary: A 1-sentence description of this author (what they're known for, their focus area)

Return JSON only:
{{
  "screen_name": {{
    "category": "category-id",
    "confidence": "high|medium|low",
    "summary": "One sentence description"
  }}
}}

AUTHORS:
"""
        for screen_name, author in batch:
            # Get sample tweets
            sample_tweets = []
            for tid in author["tweet_ids"][:5]:
                if tid in tweet_lookup:
                    sample_tweets.append(tweet_lookup[tid].get("Full Text", "")[:100])

            batch_prompt += f"\n@{author['screen_name']} ({author['followers']} followers, {author['bookmark_count']} bookmarks)"
            batch_prompt += f"\n  Bio: {author['description'][:200] if author['description'] else 'N/A'}"
            if sample_tweets:
                batch_prompt += f"\n  Sample tweets: {'; '.join(sample_tweets)}"
            batch_prompt += "\n"

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=3000,
            messages=[{"role": "user", "content": batch_prompt}]
        )

        try:
            result_text = response.content[0].text
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]
            batch_results = json.loads(result_text)

            for screen_name_key, categorization in batch_results.items():
                # Match screen name (case-insensitive)
                screen_name_lower = screen_name_key.lstrip("@").lower()
                if screen_name_lower in authors:
                    authors[screen_name_lower]["category"] = categorization.get("category")
                    authors[screen_name_lower]["category_confidence"] = categorization.get("confidence")
                    authors[screen_name_lower]["summary"] = categorization.get("summary")
        except (json.JSONDecodeError, IndexError) as e:
            print(f"  Warning: Error parsing batch: {e}")

    return authors, author_categories


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
        .video-thumbnail {{
            display: inline-block;
            text-decoration: none;
        }}
        .video-placeholder {{
            width: 280px;
            height: 160px;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border-radius: 12px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 10px;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .video-placeholder:hover {{
            transform: scale(1.02);
            box-shadow: 0 4px 20px rgba(29, 155, 240, 0.3);
        }}
        .play-icon {{
            font-size: 2.5em;
            color: #1d9bf0;
        }}
        .video-label {{
            color: #8899a6;
            font-size: 0.9em;
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
        .loading-indicator {{
            text-align: center;
            padding: 20px;
            color: var(--secondary);
        }}
        .loading-indicator.done {{
            color: var(--secondary);
            font-size: 0.9em;
        }}
        #scroll-sentinel {{
            height: 1px;
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
        <a href="../authors/index.html">Authors</a>
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
        # Skip thumbnail files
        if media_file.name.startswith("thumb_"):
            continue

        rel_path = f"../../media/{tweet_id}/{media_file.name}"
        if media_file.suffix.lower() in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
            html_parts.append(f'<img src="{rel_path}" alt="Tweet media" loading="lazy">')
        elif media_file.suffix.lower() in [".mp4", ".webm", ".mov"]:
            # Check for thumbnail
            thumb_path = tweet_media_dir / f"thumb_{media_file.stem}.jpg"
            if thumb_path.exists():
                poster_rel = f"../../media/{tweet_id}/thumb_{media_file.stem}.jpg"
                html_parts.append(f'<video src="{rel_path}" poster="{poster_rel}" controls preload="none"></video>')
            else:
                html_parts.append(f'<video src="{rel_path}" controls preload="metadata"></video>')
    html_parts.append('</div>')

    return "\n".join(html_parts) if len(html_parts) > 2 else ""


def render_media_html_server(tweet_id: str, media_dir: Path) -> str:
    """Render HTML for tweet media using absolute server paths.
    For nginx serving at /media/bookmarks/{tweet_id}/
    """
    tweet_media_dir = media_dir / tweet_id
    if not tweet_media_dir.exists():
        return ""

    media_files = list(tweet_media_dir.iterdir())
    if not media_files:
        return ""

    html_parts = ['<div class="tweet-media">']
    for media_file in media_files:
        # Skip thumbnail files
        if media_file.name.startswith("thumb_"):
            continue

        # Absolute path for server - nginx serves /media/bookmarks/ from /app/bookmarks-media/
        abs_path = f"/media/bookmarks/{tweet_id}/{media_file.name}"
        if media_file.suffix.lower() in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
            html_parts.append(f'<img src="{abs_path}" alt="Tweet media" loading="lazy">')
        elif media_file.suffix.lower() in [".mp4", ".webm", ".mov"]:
            # Check for thumbnail
            thumb_path = tweet_media_dir / f"thumb_{media_file.stem}.jpg"
            if thumb_path.exists():
                poster_abs = f"/media/bookmarks/{tweet_id}/thumb_{media_file.stem}.jpg"
                html_parts.append(f'<video src="{abs_path}" poster="{poster_abs}" controls preload="none"></video>')
            else:
                html_parts.append(f'<video src="{abs_path}" controls preload="metadata"></video>')
    html_parts.append('</div>')

    return "\n".join(html_parts) if len(html_parts) > 2 else ""


def render_media_html_cdn(bookmark: dict) -> str:
    """Render HTML for tweet media using Twitter CDN URLs.
    Videos are shown as thumbnails with play overlay linking to tweet (Twitter blocks video CDN).
    """
    media_urls = bookmark.get("Media URLs", "")
    media_types = bookmark.get("Media Types", "")
    tweet_url = bookmark.get("Tweet URL", "")

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
            # Video: show thumbnail placeholder with play button linking to tweet
            html_parts.append(f'''<a href="{tweet_url}" target="_blank" class="video-thumbnail" title="View video on X">
    <div class="video-placeholder">
        <span class="play-icon">▶</span>
        <span class="video-label">Video - View on X</span>
    </div>
</a>''')
        else:
            html_parts.append(f'<img src="{url}" alt="Tweet media" loading="lazy">')
    html_parts.append('</div>')

    return "\n".join(html_parts) if len(html_parts) > 2 else ""


def generate_tweets_json(bookmarks: list[dict], categories_data: dict | None,
                         media_mode: str = "local") -> list[dict]:
    """Generate JSON data for tweets, suitable for infinite scroll.

    media_mode: "local" (relative paths), "server" (absolute /media/bookmarks/), "cdn" (Twitter CDN)
    """
    tweets_data = []

    for bookmark in bookmarks:
        tweet_id = bookmark.get("Tweet Id", "")
        if not tweet_id:
            continue

        # Parse date
        date_str = bookmark.get("Created At", "")
        date_iso = ""
        date_display = date_str
        try:
            dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
            date_iso = dt.isoformat()
            date_display = dt.strftime("%b %d, %Y at %H:%M")
        except ValueError:
            pass

        # Get categories for this tweet
        categories = []
        if categories_data:
            tweet_cats = categories_data.get("tweet_categories", {}).get(tweet_id, [])
            for cat_id in tweet_cats:
                cat_name = categories_data.get("categories", {}).get(cat_id, {}).get("name", cat_id)
                categories.append({"id": cat_id, "name": cat_name})

        # Get media files
        media = []
        tweet_media_dir = MASTER_MEDIA_DIR / tweet_id
        if tweet_media_dir.exists():
            for media_file in tweet_media_dir.iterdir():
                # Skip thumbnail files
                if media_file.name.startswith("thumb_"):
                    continue

                # Determine path based on mode
                if media_mode == "server":
                    src = f"/media/bookmarks/{tweet_id}/{media_file.name}"
                    poster_base = f"/media/bookmarks/{tweet_id}"
                elif media_mode == "cdn":
                    # For CDN, use Twitter URLs from bookmark data
                    src = None  # Will handle separately
                    poster_base = None
                else:  # local
                    src = f"media/{tweet_id}/{media_file.name}"
                    poster_base = f"media/{tweet_id}"

                if src:
                    if media_file.suffix.lower() in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                        media.append({"type": "image", "src": src})
                    elif media_file.suffix.lower() in [".mp4", ".webm", ".mov"]:
                        # Check for thumbnail
                        thumb_name = f"thumb_{media_file.stem}.jpg"
                        thumb_path = tweet_media_dir / thumb_name
                        poster = f"{poster_base}/{thumb_name}" if thumb_path.exists() else None
                        media.append({"type": "video", "src": src, "poster": poster})

        # For CDN mode, use Twitter URLs
        if media_mode == "cdn":
            media_urls = bookmark.get("Media URLs", "")
            media_types = bookmark.get("Media Types", "")
            if media_urls:
                urls = [u.strip() for u in media_urls.split(",") if u.strip()]
                types = [t.strip() for t in media_types.split(",")] if media_types else []
                media = []
                for i, url in enumerate(urls):
                    media_type = types[i] if i < len(types) else ""
                    if media_type == "video" or any(ext in url.lower() for ext in ['.mp4', '.webm', '.mov']):
                        media.append({"type": "video", "src": url, "tweet_url": bookmark.get("Tweet URL", "")})
                    else:
                        media.append({"type": "image", "src": url})

        tweet_data = {
            "id": tweet_id,
            "author": f"@{bookmark.get('User Screen Name', 'unknown')}",
            "author_name": bookmark.get("User Name", "Unknown"),
            "avatar": bookmark.get("User Avatar Url", ""),
            "text": bookmark.get("Full Text", ""),
            "date": date_iso,
            "date_display": date_display,
            "media": media,
            "categories": categories,
            "likes": bookmark.get("Favorite Count", 0),
            "retweets": bookmark.get("Retweet Count", 0),
            "replies": bookmark.get("Reply Count", 0),
            "tweet_url": f"https://x.com/{bookmark.get('User Screen Name', 'unknown')}/status/{tweet_id}"
        }
        tweets_data.append(tweet_data)

    return tweets_data


def render_tweet_card(bookmark: dict, categories_data: dict | None = None,
                      include_detail_link: bool = True, use_cdn: bool = False,
                      use_server: bool = False) -> str:
    """Render a tweet card HTML.

    Media rendering modes:
    - use_cdn=True: Twitter CDN URLs (for GitHub Pages)
    - use_server=True: Absolute /media/bookmarks/ paths (for EC2 server)
    - Both False: Relative ../media/ paths (for local viewing)
    """
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

    # Select media rendering mode
    if use_cdn:
        media_html = render_media_html_cdn(bookmark)
    elif use_server:
        media_html = render_media_html_server(tweet_id, MASTER_MEDIA_DIR)
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


# ==================== Author HTML Generation ====================

def generate_authors_html(authors_data: dict, bookmarks: list[dict]) -> None:
    """Generate authors listing pages"""
    authors_dir = MASTER_HTML_DIR / "authors"
    authors_dir.mkdir(parents=True, exist_ok=True)

    authors = authors_data.get("authors", {})
    author_categories = authors_data.get("author_categories", {})
    tweet_lookup = {b["Tweet Id"]: b for b in bookmarks}

    # Sort authors alphabetically by screen_name
    sorted_authors = sorted(authors.values(), key=lambda x: x["screen_name"].lower())

    # Build category filter buttons
    category_counts = defaultdict(int)
    for author in authors.values():
        cat = author.get("category")
        if cat:
            category_counts[cat] += 1
        else:
            category_counts["uncategorized"] += 1

    filter_buttons = ['<button class="filter-btn active" onclick="filterAuthors(\'all\')">All</button>']
    for cat_id in sorted(author_categories.keys()):
        count = category_counts.get(cat_id, 0)
        if count > 0:
            cat_name = author_categories[cat_id].get("name", cat_id)
            filter_buttons.append(
                f'<button class="filter-btn" onclick="filterAuthors(\'{cat_id}\')">{cat_name} ({count})</button>'
            )
    if category_counts.get("uncategorized", 0) > 0:
        filter_buttons.append(
            f'<button class="filter-btn" onclick="filterAuthors(\'uncategorized\')">Uncategorized ({category_counts["uncategorized"]})</button>'
        )

    # Build author cards
    author_cards = []
    for author in sorted_authors:
        cat = author.get("category") or "uncategorized"
        cat_name = author_categories.get(cat, {}).get("name", "Uncategorized") if cat != "uncategorized" else "Uncategorized"

        # Category badge
        cat_badge = f'<span class="category-tag">{cat_name}</span>' if cat != "uncategorized" else '<span class="category-tag" style="background: var(--secondary);">Uncategorized</span>'

        # Verified badge
        verified_badge = ' <span style="color: #1d9bf0;">&#10003;</span>' if author.get("verified") else ""

        # Summary or bio snippet
        summary = author.get("summary") or (author.get("description", "")[:100] + "..." if len(author.get("description", "")) > 100 else author.get("description", ""))

        author_cards.append(f'''
<div class="author-card" data-category="{cat}" data-name="{author['screen_name'].lower()}">
    <div class="author-header">
        <img class="avatar" src="{author.get('avatar', '')}" alt="{author['name']}" onerror="this.style.display='none'">
        <div class="author-info">
            <div class="author-name">{author['name']}{verified_badge}</div>
            <div class="author-handle">
                <a href="https://x.com/{author['screen_name']}" target="_blank">@{author['screen_name']}</a>
            </div>
        </div>
        <div class="author-stats">
            <span>{author['bookmark_count']} bookmarks</span>
            <span>{author['followers']:,} followers</span>
        </div>
    </div>
    <div class="author-summary">{summary}</div>
    <div class="author-meta">
        {cat_badge}
        <a href="{author['screen_name'].lower()}.html">{author['bookmark_count']} bookmarked tweets</a>
    </div>
</div>
''')

    # Additional CSS for authors page
    authors_css = '''
        .author-card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 15px;
            margin-bottom: 15px;
        }
        .author-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
        }
        .author-stats {
            margin-left: auto;
            text-align: right;
            color: var(--secondary);
            font-size: 0.85em;
        }
        .author-stats span {
            display: block;
        }
        .author-summary {
            color: var(--secondary);
            font-size: 0.9em;
            margin-bottom: 10px;
        }
        .author-meta {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .author-search {
            width: 100%;
            padding: 10px;
            margin-bottom: 15px;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: var(--card-bg);
            color: var(--text);
            font-size: 1em;
        }
    '''

    content = f'''
<style>{authors_css}</style>
<h1>Authors</h1>
<p class="meta">{len(authors)} authors whose tweets you've bookmarked</p>

<input type="text" class="author-search" id="authorSearch" placeholder="Search authors..." oninput="searchAuthors(this.value)">

<div class="filter-bar">
    {chr(10).join(filter_buttons)}
</div>

<div id="authorList">
{chr(10).join(author_cards)}
</div>

<script>
function filterAuthors(category) {{
    const cards = document.querySelectorAll('.author-card');
    const buttons = document.querySelectorAll('.filter-btn');

    buttons.forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');

    cards.forEach(card => {{
        if (category === 'all' || card.dataset.category === category) {{
            card.style.display = 'block';
        }} else {{
            card.style.display = 'none';
        }}
    }});
}}

function searchAuthors(query) {{
    const cards = document.querySelectorAll('.author-card');
    const lowerQuery = query.toLowerCase();

    cards.forEach(card => {{
        const name = card.dataset.name;
        const text = card.textContent.toLowerCase();
        if (name.includes(lowerQuery) || text.includes(lowerQuery)) {{
            card.style.display = 'block';
        }} else {{
            card.style.display = 'none';
        }}
    }});

    // Reset filter buttons
    document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelector('.filter-btn').classList.add('active');
}}
</script>
'''

    page_html = HTML_BASE.format(title="Authors", content=content)
    with open(authors_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(page_html)

    print(f"Generated authors/index.html with {len(authors)} authors")

    # Generate individual author pages (for authors with 5+ bookmarks)
    significant_authors = [a for a in authors.values() if a["bookmark_count"] >= 5]
    for author in significant_authors:
        generate_author_page(author, tweet_lookup, author_categories, authors_dir)

    print(f"Generated {len(significant_authors)} individual author pages")


def generate_author_page(author: dict, tweet_lookup: dict, author_categories: dict, authors_dir: Path) -> None:
    """Generate individual author page with their bookmarked tweets"""
    screen_name = author["screen_name"].lower()
    cat = author.get("category") or "uncategorized"
    cat_name = author_categories.get(cat, {}).get("name", "Uncategorized") if cat != "uncategorized" else "Uncategorized"

    # Get tweets for this author
    tweets = [tweet_lookup[tid] for tid in author["tweet_ids"] if tid in tweet_lookup]
    tweets.sort(
        key=lambda x: parse_tweet_date(x.get("Created At", "")) or datetime.min.replace(tzinfo=None),
        reverse=True
    )

    # Render tweet cards
    tweets_html = "\n".join(render_tweet_card(t, None, include_detail_link=True) for t in tweets)

    # Verified badge
    verified_badge = ' <span style="color: #1d9bf0;">&#10003;</span>' if author.get("verified") else ""

    # Category badge
    cat_badge = f'<span class="category-tag">{cat_name}</span>'

    content = f'''
<div class="author-profile">
    <div class="tweet-header">
        <img class="avatar" src="{author.get('avatar', '')}" alt="{author['name']}" onerror="this.style.display='none'">
        <div class="author-info">
            <div class="author-name">{author['name']}{verified_badge}</div>
            <div class="author-handle">
                <a href="https://x.com/{author['screen_name']}" target="_blank">@{author['screen_name']}</a>
            </div>
        </div>
    </div>
    <p style="margin: 10px 0;">{author.get('description', '')}</p>
    <div style="color: var(--secondary); font-size: 0.9em; margin-bottom: 10px;">
        {author['followers']:,} followers | {author.get('location', '') or 'Location unknown'}
    </div>
    <div style="margin-bottom: 20px;">
        {cat_badge}
        {f'<p style="font-style: italic; margin-top: 5px;">{author.get("summary", "")}</p>' if author.get("summary") else ""}
    </div>
</div>

<h2>{len(tweets)} Bookmarked Tweets</h2>
<div class="tweet-list">
{tweets_html}
</div>
'''

    page_html = HTML_BASE.format(title=f"@{author['screen_name']} - Authors", content=content)
    with open(authors_dir / f"{screen_name}.html", "w", encoding="utf-8") as f:
        f.write(page_html)


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

    # Generate main index (chronological) with infinite scroll
    print("Generating main index with infinite scroll...")

    # Create data directory and export tweets JSON
    data_dir = MASTER_HTML_DIR / "data"
    data_dir.mkdir(exist_ok=True)

    tweets_json = generate_tweets_json(bookmarks, categories_data, media_mode="local")
    with open(data_dir / "tweets.json", "w", encoding="utf-8") as f:
        json.dump(tweets_json, f)
    print(f"  Exported {len(tweets_json)} tweets to data/tweets.json")

    # Create compact search index for suggestions
    search_suggestions = json.dumps(search_index.get("suggestions", {}))

    index_content = f"""
<h1>Twitter Bookmarks</h1>
<p class="meta"><span id="shown-count">0</span> of {len(bookmarks)} bookmarks</p>
<div class="search-container">
    <input type="text" id="search-input" class="search-box" placeholder="Search tweets... (type @ for profiles)" autocomplete="off">
    <div id="search-suggestions" class="search-suggestions hidden"></div>
</div>
<div id="search-results" class="search-results hidden"></div>
<div id="tweets-container" class="tweet-list"></div>
<div id="scroll-sentinel"></div>
<div id="loading-indicator" class="loading-indicator">Loading...</div>
<script>
const SUGGESTIONS = {search_suggestions};
const BATCH_SIZE = 50;
const CATEGORIES_PATH = 'categories/';

let allTweets = [];
let filteredTweets = [];
let displayedCount = 0;
let isLoading = false;
let searchTimeout = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', init);

async function init() {{
    try {{
        const response = await fetch('data/tweets.json');
        allTweets = await response.json();
        filteredTweets = allTweets;
        loadMoreTweets();
        setupInfiniteScroll();
        setupSearch();
    }} catch (e) {{
        console.error('Failed to load tweets:', e);
        document.getElementById('loading-indicator').textContent = 'Failed to load tweets';
    }}
}}

function loadMoreTweets() {{
    if (isLoading || displayedCount >= filteredTweets.length) {{
        updateLoadingIndicator();
        return;
    }}
    isLoading = true;

    const batch = filteredTweets.slice(displayedCount, displayedCount + BATCH_SIZE);
    const container = document.getElementById('tweets-container');
    const fragment = document.createDocumentFragment();

    batch.forEach(tweet => {{
        fragment.appendChild(renderTweetCard(tweet));
    }});

    container.appendChild(fragment);
    displayedCount += batch.length;
    isLoading = false;
    updateShownCount();
    updateLoadingIndicator();
}}

function updateShownCount() {{
    document.getElementById('shown-count').textContent = displayedCount;
}}

function updateLoadingIndicator() {{
    const indicator = document.getElementById('loading-indicator');
    if (displayedCount >= filteredTweets.length) {{
        indicator.textContent = filteredTweets.length === allTweets.length
            ? 'All tweets loaded'
            : `${{filteredTweets.length}} matches loaded`;
        indicator.classList.add('done');
    }} else {{
        indicator.textContent = 'Loading...';
        indicator.classList.remove('done');
    }}
}}

function setupInfiniteScroll() {{
    const sentinel = document.getElementById('scroll-sentinel');
    const observer = new IntersectionObserver(entries => {{
        if (entries[0].isIntersecting && displayedCount < filteredTweets.length) {{
            loadMoreTweets();
        }}
    }}, {{ rootMargin: '200px' }});
    observer.observe(sentinel);
}}

function setupSearch() {{
    const searchInput = document.getElementById('search-input');
    const suggestionsDiv = document.getElementById('search-suggestions');
    let selectedIdx = -1;

    searchInput.addEventListener('input', (e) => {{
        showSuggestions(e.target.value);
        // Debounce search
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => filterTweets(e.target.value), 200);
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

    function showSuggestions(query) {{
        if (!query || query.length < 2) {{
            suggestionsDiv.classList.add('hidden');
            return;
        }}
        const isProfile = query.startsWith('@');
        const searchTerm = isProfile ? query.slice(1).toLowerCase() : query.toLowerCase();
        const source = isProfile ? SUGGESTIONS.profiles : SUGGESTIONS.words;
        const matches = (source || []).filter(s => {{
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

    document.addEventListener('click', (e) => {{
        if (!e.target.closest('.search-container')) {{
            suggestionsDiv.classList.add('hidden');
        }}
    }});
}}

function filterTweets(query) {{
    query = (query || '').toLowerCase().trim();
    const resultsDiv = document.getElementById('search-results');

    if (!query) {{
        filteredTweets = allTweets;
    }} else {{
        const isProfile = query.startsWith('@');
        const searchTerm = isProfile ? query.slice(1) : query;
        filteredTweets = allTweets.filter(t => {{
            if (isProfile) {{
                return t.author.toLowerCase().includes(searchTerm);
            }}
            return t.text.toLowerCase().includes(searchTerm) ||
                   t.author.toLowerCase().includes(searchTerm) ||
                   t.author_name.toLowerCase().includes(searchTerm);
        }});
    }}

    // Reset and re-render
    document.getElementById('tweets-container').innerHTML = '';
    displayedCount = 0;
    loadMoreTweets();

    if (query) {{
        resultsDiv.textContent = `${{filteredTweets.length}} bookmark${{filteredTweets.length !== 1 ? 's' : ''}} found`;
        resultsDiv.classList.remove('hidden');
    }} else {{
        resultsDiv.classList.add('hidden');
    }}
}}

function renderTweetCard(tweet) {{
    const card = document.createElement('article');
    card.className = 'tweet-card';

    const categoriesHtml = tweet.categories.map(c =>
        `<a href="${{CATEGORIES_PATH}}${{c.id}}.html" class="category-tag">${{c.name}}</a>`
    ).join(' ');

    const mediaHtml = renderMedia(tweet.media, tweet.tweet_url);

    card.innerHTML = `
        <div class="tweet-header">
            <img class="avatar" src="${{tweet.avatar}}" alt="${{tweet.author_name}}" onerror="this.style.display='none'">
            <div class="author-info">
                <div class="author-name">${{escapeHtml(tweet.author_name)}}</div>
                <div class="author-handle">
                    <a href="https://x.com/${{tweet.author.slice(1)}}" target="_blank">${{tweet.author}}</a>
                </div>
            </div>
        </div>
        <div class="tweet-text">${{escapeHtml(tweet.text)}}</div>
        ${{mediaHtml}}
        ${{categoriesHtml ? `<div class="tweet-categories">${{categoriesHtml}}</div>` : ''}}
        <div class="tweet-stats">
            <span>${{tweet.likes}} likes</span>
            <span>${{tweet.retweets}} retweets</span>
            <span>${{tweet.replies}} replies</span>
            <span>${{tweet.date_display}}</span>
        </div>
        <div class="tweet-links">
            <a href="${{tweet.tweet_url}}" target="_blank">View on X</a>
            | <a href="tweets/${{tweet.id}}.html">Details</a>
        </div>
    `;
    return card;
}}

function renderMedia(media, tweetUrl) {{
    if (!media || media.length === 0) return '';
    const items = media.map(m => {{
        if (m.type === 'video') {{
            if (m.src && !m.src.startsWith('http')) {{
                const posterAttr = m.poster ? ` poster="${{m.poster}}"` : '';
                const preload = m.poster ? 'none' : 'metadata';
                return `<video src="${{m.src}}"${{posterAttr}} controls preload="${{preload}}"></video>`;
            }}
            // CDN video - show placeholder
            return `<a href="${{tweetUrl}}" target="_blank" class="video-thumbnail" title="View video on X">
                <div class="video-placeholder"><span class="play-icon">▶</span><span class="video-label">Video - View on X</span></div>
            </a>`;
        }}
        return `<img src="${{m.src}}" alt="Tweet media" loading="lazy">`;
    }}).join('');
    return `<div class="tweet-media">${{items}}</div>`;
}}

function escapeHtml(text) {{
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}}
</script>
"""

    # Fix nav links for index page
    index_html = HTML_BASE.format(title="Twitter Bookmarks", content=index_content)
    index_html = index_html.replace('../index.html', 'index.html')
    index_html = index_html.replace('../categories/', 'categories/')
    index_html = index_html.replace('../timeline/', 'timeline/')
    index_html = index_html.replace('../stories/', 'stories/')

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

    # Build comprehensive timeline data structure
    # {year: {total, categories: {cat_id: count}, months: {mm: {total, categories}}}}
    timeline_data: dict = {}
    by_period: dict[str, list[dict]] = defaultdict(list)

    for bookmark in bookmarks:
        dt = parse_tweet_date(bookmark.get("Created At", ""))
        if not dt:
            continue

        year = str(dt.year)
        month = f"{dt.month:02d}"
        tweet_id = bookmark.get("Tweet Id", "")

        # Get categories for this tweet
        tweet_cats = []
        if categories_data:
            tweet_cats = categories_data.get("tweet_categories", {}).get(tweet_id, [])

        # Initialize year if needed
        if year not in timeline_data:
            timeline_data[year] = {"total": 0, "categories": defaultdict(int), "months": {}}

        # Initialize month if needed
        if month not in timeline_data[year]["months"]:
            timeline_data[year]["months"][month] = {"total": 0, "categories": defaultdict(int)}

        # Update counts
        timeline_data[year]["total"] += 1
        timeline_data[year]["months"][month]["total"] += 1

        for cat_id in tweet_cats:
            timeline_data[year]["categories"][cat_id] += 1
            timeline_data[year]["months"][month]["categories"][cat_id] += 1

        # Also keep old structure for month pages
        periods = get_time_periods(dt)
        by_period[f"month-{periods['month']}"].append(bookmark)

    # Load stories data for story links
    stories_available = {}
    if MASTER_STORIES.exists():
        stories_data = load_stories()
        for cat_id, years_dict in stories_data.get("category_years", {}).items():
            for year in years_dict.keys():
                if year not in stories_available:
                    stories_available[year] = []
                stories_available[year].append(cat_id)

    # Get category names lookup
    cat_names = {}
    if categories_data:
        for cat_id, cat_info in categories_data.get("categories", {}).items():
            cat_names[cat_id] = cat_info.get("name", cat_id)

    # Generate collapsible Timeline index
    years = sorted(timeline_data.keys(), reverse=True)

    timeline_content = "<h1>Timeline</h1>\n"
    timeline_content += f'<p class="meta">{len(bookmarks)} bookmarks across {len(years)} years</p>\n'

    for year in years:
        year_data = timeline_data[year]
        total = year_data["total"]

        # Top categories for this year (sorted by count)
        top_cats = sorted(year_data["categories"].items(), key=lambda x: x[1], reverse=True)[:5]
        cats_html = " ".join(
            f'<span class="category-tag">{cat_names.get(cat_id, cat_id)} ({count})</span>'
            for cat_id, count in top_cats
        )

        # Stories available for this year
        year_stories = stories_available.get(year, [])
        stories_html = ""
        if year_stories:
            stories_html = f'<div class="stories-available">{len(year_stories)} stories</div>'

        # Months summary
        months_sorted = sorted(year_data["months"].keys(), reverse=True)
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        timeline_content += f'''
<div class="timeline-year" data-year="{year}">
    <div class="year-header" onclick="toggleYear('{year}')">
        <span class="year-toggle">▶</span>
        <span class="year-name">{year}</span>
        <span class="year-count">{total} bookmarks</span>
        {stories_html}
    </div>
    <div class="year-categories">{cats_html}</div>
    <div class="year-months hidden" id="months-{year}">
'''

        for mm in months_sorted:
            month_data = year_data["months"][mm]
            month_total = month_data["total"]
            month_name = month_names[int(mm) - 1]

            # Top categories for this month
            month_top_cats = sorted(month_data["categories"].items(), key=lambda x: x[1], reverse=True)[:3]
            month_cats_html = " ".join(
                f'<span class="category-tag small">{cat_names.get(cat_id, cat_id)} ({count})</span>'
                for cat_id, count in month_top_cats
            )

            timeline_content += f'''
        <div class="month-card">
            <a href="{year}/{mm}/index.html" class="month-link">
                <span class="month-name">{month_name}</span>
                <span class="month-count">{month_total}</span>
            </a>
            <div class="month-categories">{month_cats_html}</div>
        </div>
'''

        timeline_content += "    </div>\n</div>\n"

    # Add JavaScript for collapsible behavior
    timeline_content += """
<script>
function toggleYear(year) {
    const monthsDiv = document.getElementById('months-' + year);
    const yearDiv = document.querySelector(`.timeline-year[data-year="${year}"]`);
    const toggle = yearDiv.querySelector('.year-toggle');

    if (monthsDiv.classList.contains('hidden')) {
        monthsDiv.classList.remove('hidden');
        toggle.textContent = '▼';
        yearDiv.classList.add('expanded');
    } else {
        monthsDiv.classList.add('hidden');
        toggle.textContent = '▶';
        yearDiv.classList.remove('expanded');
    }
}
</script>
<style>
.timeline-year {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 15px;
    overflow: hidden;
}
.year-header {
    padding: 15px 20px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 15px;
    background: var(--card-bg);
    transition: background 0.2s;
}
.year-header:hover {
    background: var(--bg);
}
.year-toggle {
    font-size: 12px;
    color: var(--secondary);
    transition: transform 0.2s;
}
.timeline-year.expanded .year-toggle {
    transform: rotate(90deg);
}
.year-name {
    font-size: 1.4em;
    font-weight: bold;
}
.year-count {
    color: var(--secondary);
}
.stories-available {
    background: var(--link);
    color: white;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.85em;
    margin-left: auto;
}
.year-categories {
    padding: 0 20px 15px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}
.year-months {
    border-top: 1px solid var(--border);
    padding: 15px 20px;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 10px;
}
.month-card {
    background: var(--bg);
    border-radius: 8px;
    padding: 12px;
}
.month-card .month-link {
    display: flex;
    justify-content: space-between;
    align-items: center;
    text-decoration: none;
    color: var(--text);
    font-weight: 500;
}
.month-card .month-link:hover {
    color: var(--link);
}
.month-count {
    background: var(--border);
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 0.85em;
}
.month-categories {
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
}
.category-tag.small {
    font-size: 0.75em;
    padding: 2px 6px;
}
</style>
"""

    timeline_html = HTML_BASE.format(title="Timeline", content=timeline_content)
    timeline_html = timeline_html.replace('../index.html', '../index.html')
    with open(MASTER_HTML_DIR / "timeline" / "index.html", "w", encoding="utf-8") as f:
        f.write(timeline_html)

    # Generate month pages (for when users click through)
    for year in years:
        year_dir = MASTER_HTML_DIR / "timeline" / year
        year_dir.mkdir(exist_ok=True)

        for mm in timeline_data[year]["months"].keys():
            month_key = f"{year}-{mm}"
            month_tweets = by_period.get(f"month-{month_key}", [])
            month_name = datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")

            month_dir = year_dir / mm
            month_dir.mkdir(exist_ok=True)

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


def cmd_authors(args: argparse.Namespace) -> None:
    """Manage author profiles and AI categorization"""
    subcommand = getattr(args, 'authors_command', None)

    # Load bookmarks
    if not MASTER_JSON.exists():
        print("Master JSON not found. Run 'merge' first.")
        return

    with open(MASTER_JSON, "r", encoding="utf-8") as f:
        bookmarks = json.load(f)

    print(f"Loaded {len(bookmarks)} bookmarks")

    # Build author profiles from bookmarks
    print("Building author profiles...")
    authors = build_author_profiles(bookmarks)
    print(f"Found {len(authors)} unique authors")

    # Load existing authors data to preserve categorizations
    existing_data = load_authors()
    existing_authors = existing_data.get("authors", {})
    existing_categories = existing_data.get("author_categories", {})

    # Merge with existing categorizations
    for screen_name, author in authors.items():
        if screen_name in existing_authors:
            existing = existing_authors[screen_name]
            author["category"] = existing.get("category")
            author["category_confidence"] = existing.get("category_confidence")
            author["summary"] = existing.get("summary")

    if subcommand == "categorize" or subcommand is None:
        # Run AI categorization
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("Error: ANTHROPIC_API_KEY environment variable not set")
            print("Set it with: export ANTHROPIC_API_KEY='your-key-here'")
            if subcommand == "categorize":
                return
        else:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)

                min_bookmarks = getattr(args, 'min_bookmarks', 3)
                print(f"\n=== Categorizing authors with {min_bookmarks}+ bookmarks ===")
                authors, author_categories = categorize_authors_ai(client, authors, bookmarks, min_bookmarks)

                # Save authors data
                authors_data = {
                    "generated_at": datetime.now().isoformat(),
                    "author_categories": author_categories,
                    "authors": authors
                }
                save_authors(authors_data)
                print(f"\nAuthors saved to {MASTER_AUTHORS}")

                # Stats
                categorized = sum(1 for a in authors.values() if a.get("category"))
                print(f"Categorized: {categorized}/{len(authors)} authors")

            except ImportError:
                print("Error: anthropic package not installed")
                print("Install with: pip install anthropic")
                if subcommand == "categorize":
                    return

    if subcommand == "generate" or subcommand is None:
        # Generate HTML pages
        print("\n=== Generating author pages ===")

        # Make sure we have authors data
        if not MASTER_AUTHORS.exists():
            # Save what we have even without categorization
            authors_data = {
                "generated_at": datetime.now().isoformat(),
                "author_categories": existing_categories,
                "authors": authors
            }
            save_authors(authors_data)

        with open(MASTER_AUTHORS, "r", encoding="utf-8") as f:
            authors_data = json.load(f)

        generate_authors_html(authors_data, bookmarks)

    print("\n=== Authors complete ===")


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
    (html_dir / "authors").mkdir(exist_ok=True)

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


def add_newgen_link(html: str) -> str:
    """Add 'New-Gen' link to navbar for server version"""
    # Add New-Gen link after Authors link (handles both relative and absolute paths)
    html = html.replace(
        '<a href="../authors/index.html">Authors</a>',
        '<a href="../authors/index.html">Authors</a>\n        <a href="/new-gen/">New-Gen</a>'
    )
    html = html.replace(
        '<a href="/authors/index.html">Authors</a>',
        '<a href="/authors/index.html">Authors</a>\n        <a href="/new-gen/">New-Gen</a>'
    )
    # Handle authors pages where Authors link is self-referential
    html = html.replace(
        '<a href="index.html">Authors</a>',
        '<a href="index.html">Authors</a>\n        <a href="/new-gen/">New-Gen</a>'
    )
    # Also handle stories pages that haven't been regenerated yet
    html = html.replace(
        '<a href="../stories/index.html">Stories</a>\n        <a href="../authors/index.html">Authors</a>',
        '<a href="../stories/index.html">Stories</a>\n        <a href="../authors/index.html">Authors</a>\n        <a href="/new-gen/">New-Gen</a>'
    )
    return html


def fix_paths_for_server(html: str) -> str:
    """Fix relative paths to absolute paths for server root serving"""
    # Convert relative nav links to absolute
    html = html.replace('href="../index.html"', 'href="/"')
    html = html.replace('href="../categories/', 'href="/categories/')
    html = html.replace('href="../timeline/', 'href="/timeline/')
    html = html.replace('href="../stories/', 'href="/stories/')
    html = html.replace('href="../authors/', 'href="/authors/')
    html = html.replace('href="../tweets/', 'href="/tweets/')
    return html


def generate_html_server(output_dir: Path, bookmarks: list[dict], categories_data: dict,
                         stories_data: dict) -> None:
    """Generate HTML pages for server deployment with local media paths"""
    html_dir = output_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    (html_dir / "categories").mkdir(exist_ok=True)
    (html_dir / "timeline").mkdir(exist_ok=True)
    (html_dir / "tweets").mkdir(exist_ok=True)
    (html_dir / "stories").mkdir(exist_ok=True)
    (html_dir / "authors").mkdir(exist_ok=True)

    tweet_lookup = {b["Tweet Id"]: b for b in bookmarks}

    # Generate main index (chronological) with infinite scroll
    print("Generating main index with infinite scroll...")

    # Create data directory and export tweets JSON
    data_dir = html_dir / "data"
    data_dir.mkdir(exist_ok=True)

    sorted_bookmarks = sorted(
        bookmarks,
        key=lambda x: parse_tweet_date(x.get("Created At", "")) or datetime.min.replace(tzinfo=None),
        reverse=True
    )
    tweets_json = generate_tweets_json(sorted_bookmarks, categories_data, media_mode="server")
    with open(data_dir / "tweets.json", "w", encoding="utf-8") as f:
        json.dump(tweets_json, f)
    print(f"  Exported {len(tweets_json)} tweets to data/tweets.json")

    # Build search index for suggestions
    search_index = build_search_index(bookmarks)
    search_suggestions = json.dumps(search_index.get("suggestions", {}))

    index_content = f"""
<h1>Twitter Bookmarks</h1>
<p class="meta"><span id="shown-count">0</span> of {len(bookmarks)} bookmarks</p>
<div class="search-container">
    <input type="text" id="search-input" class="search-box" placeholder="Search tweets... (type @ for profiles)" autocomplete="off">
    <div id="search-suggestions" class="search-suggestions hidden"></div>
</div>
<div id="search-results" class="search-results hidden"></div>
<div id="tweets-container" class="tweet-list"></div>
<div id="scroll-sentinel"></div>
<div id="loading-indicator" class="loading-indicator">Loading...</div>
<script>
const SUGGESTIONS = {search_suggestions};
const BATCH_SIZE = 50;
const CATEGORIES_PATH = '/categories/';

let allTweets = [];
let filteredTweets = [];
let displayedCount = 0;
let isLoading = false;
let searchTimeout = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', init);

async function init() {{
    try {{
        const response = await fetch('/data/tweets.json');
        allTweets = await response.json();
        filteredTweets = allTweets;
        loadMoreTweets();
        setupInfiniteScroll();
        setupSearch();
    }} catch (e) {{
        console.error('Failed to load tweets:', e);
        document.getElementById('loading-indicator').textContent = 'Failed to load tweets';
    }}
}}

function loadMoreTweets() {{
    if (isLoading || displayedCount >= filteredTweets.length) {{
        updateLoadingIndicator();
        return;
    }}
    isLoading = true;

    const batch = filteredTweets.slice(displayedCount, displayedCount + BATCH_SIZE);
    const container = document.getElementById('tweets-container');
    const fragment = document.createDocumentFragment();

    batch.forEach(tweet => {{
        fragment.appendChild(renderTweetCard(tweet));
    }});

    container.appendChild(fragment);
    displayedCount += batch.length;
    isLoading = false;
    updateShownCount();
    updateLoadingIndicator();
}}

function updateShownCount() {{
    document.getElementById('shown-count').textContent = displayedCount;
}}

function updateLoadingIndicator() {{
    const indicator = document.getElementById('loading-indicator');
    if (displayedCount >= filteredTweets.length) {{
        indicator.textContent = filteredTweets.length === allTweets.length
            ? 'All tweets loaded'
            : `${{filteredTweets.length}} matches loaded`;
        indicator.classList.add('done');
    }} else {{
        indicator.textContent = 'Loading...';
        indicator.classList.remove('done');
    }}
}}

function setupInfiniteScroll() {{
    const sentinel = document.getElementById('scroll-sentinel');
    const observer = new IntersectionObserver(entries => {{
        if (entries[0].isIntersecting && displayedCount < filteredTweets.length) {{
            loadMoreTweets();
        }}
    }}, {{ rootMargin: '200px' }});
    observer.observe(sentinel);
}}

function setupSearch() {{
    const searchInput = document.getElementById('search-input');
    const suggestionsDiv = document.getElementById('search-suggestions');
    let selectedIdx = -1;

    searchInput.addEventListener('input', (e) => {{
        showSuggestions(e.target.value);
        // Debounce search
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => filterTweets(e.target.value), 200);
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

    function showSuggestions(query) {{
        if (!query || query.length < 2) {{
            suggestionsDiv.classList.add('hidden');
            return;
        }}
        const isProfile = query.startsWith('@');
        const searchTerm = isProfile ? query.slice(1).toLowerCase() : query.toLowerCase();
        const source = isProfile ? SUGGESTIONS.profiles : SUGGESTIONS.words;
        const matches = (source || []).filter(s => {{
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

    document.addEventListener('click', (e) => {{
        if (!e.target.closest('.search-container')) {{
            suggestionsDiv.classList.add('hidden');
        }}
    }});
}}

function filterTweets(query) {{
    query = (query || '').toLowerCase().trim();
    const resultsDiv = document.getElementById('search-results');

    if (!query) {{
        filteredTweets = allTweets;
    }} else {{
        const isProfile = query.startsWith('@');
        const searchTerm = isProfile ? query.slice(1) : query;
        filteredTweets = allTweets.filter(t => {{
            if (isProfile) {{
                return t.author.toLowerCase().includes(searchTerm);
            }}
            return t.text.toLowerCase().includes(searchTerm) ||
                   t.author.toLowerCase().includes(searchTerm) ||
                   t.author_name.toLowerCase().includes(searchTerm);
        }});
    }}

    // Reset and re-render
    document.getElementById('tweets-container').innerHTML = '';
    displayedCount = 0;
    loadMoreTweets();

    if (query) {{
        resultsDiv.textContent = `${{filteredTweets.length}} bookmark${{filteredTweets.length !== 1 ? 's' : ''}} found`;
        resultsDiv.classList.remove('hidden');
    }} else {{
        resultsDiv.classList.add('hidden');
    }}
}}

function renderTweetCard(tweet) {{
    const card = document.createElement('article');
    card.className = 'tweet-card';

    const categoriesHtml = tweet.categories.map(c =>
        `<a href="${{CATEGORIES_PATH}}${{c.id}}.html" class="category-tag">${{c.name}}</a>`
    ).join(' ');

    const mediaHtml = renderMedia(tweet.media, tweet.tweet_url);

    card.innerHTML = `
        <div class="tweet-header">
            <img class="avatar" src="${{tweet.avatar}}" alt="${{tweet.author_name}}" onerror="this.style.display='none'">
            <div class="author-info">
                <div class="author-name">${{escapeHtml(tweet.author_name)}}</div>
                <div class="author-handle">
                    <a href="https://x.com/${{tweet.author.slice(1)}}" target="_blank">${{tweet.author}}</a>
                </div>
            </div>
        </div>
        <div class="tweet-text">${{escapeHtml(tweet.text)}}</div>
        ${{mediaHtml}}
        ${{categoriesHtml ? `<div class="tweet-categories">${{categoriesHtml}}</div>` : ''}}
        <div class="tweet-stats">
            <span>${{tweet.likes}} likes</span>
            <span>${{tweet.retweets}} retweets</span>
            <span>${{tweet.replies}} replies</span>
            <span>${{tweet.date_display}}</span>
        </div>
        <div class="tweet-links">
            <a href="${{tweet.tweet_url}}" target="_blank">View on X</a>
            | <a href="/tweets/${{tweet.id}}.html">Details</a>
        </div>
    `;
    return card;
}}

function renderMedia(media, tweetUrl) {{
    if (!media || media.length === 0) return '';
    const items = media.map(m => {{
        if (m.type === 'video') {{
            const posterAttr = m.poster ? ` poster="${{m.poster}}"` : '';
            const preload = m.poster ? 'none' : 'metadata';
            return `<video src="${{m.src}}"${{posterAttr}} controls preload="${{preload}}"></video>`;
        }}
        return `<img src="${{m.src}}" alt="Tweet media" loading="lazy">`;
    }}).join('');
    return `<div class="tweet-media">${{items}}</div>`;
}}

function escapeHtml(text) {{
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}}
</script>
"""
    page = HTML_BASE.format(title="Twitter Bookmarks", content=index_content)
    page = fix_paths_for_server(page)
    page = add_newgen_link(page)
    page = page.replace('href="/index.html"', 'href="/"')
    with open(html_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(page)

    # Generate category index with timeline nav (matching local version)
    print("Generating category pages...")
    categories = categories_data.get("categories", {})

    # Build category timeline data
    category_timeline = build_category_timeline(bookmarks, categories_data)

    # Build stories availability map for JavaScript
    stories_available = {}
    if stories_data and stories_data.get("category_years"):
        for cat, years in stories_data.get("category_years", {}).items():
            stories_available[cat] = list(years.keys())

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
                monthLinks.push(`<a href="/stories/${{cat}}/${{year}}.html" class="month-link" style="background: var(--link); color: white;">View ${{year}} Story</a>`);
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
    page = HTML_BASE.format(title="Categories", content=cat_index_content)
    page = fix_paths_for_server(page)
    page = add_newgen_link(page)
    with open(html_dir / "categories" / "index.html", "w", encoding="utf-8") as f:
        f.write(page)

    # Generate individual category pages
    for cat_id, cat_info in categories.items():
        cat_tweets = [tweet_lookup[tid] for tid in cat_info.get("tweet_ids", []) if tid in tweet_lookup]
        cat_tweets.sort(
            key=lambda x: parse_tweet_date(x.get("Created At", "")) or datetime.min.replace(tzinfo=None),
            reverse=True
        )
        tweets_html = "\n".join(render_tweet_card(b, categories_data, use_server=True) for b in cat_tweets)
        content = f'''
<h1>{cat_info.get("name", cat_id)}</h1>
<p class="meta">{len(cat_tweets)} bookmarks</p>
<p>{cat_info.get("description", "")}</p>
<div class="tweet-list">
{tweets_html}
</div>
'''
        page = HTML_BASE.format(title=cat_info.get("name", cat_id), content=content)
        page = fix_paths_for_server(page)
        page = add_newgen_link(page)
        with open(html_dir / "categories" / f"{cat_id}.html", "w", encoding="utf-8") as f:
            f.write(page)

    # Generate stories pages if available
    if stories_data and stories_data.get("category_years"):
        print("Generating story pages...")
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

                content = fix_paths_for_server(content)
                content = add_newgen_link(content)
                # Fix media paths to absolute server paths
                content = content.replace('../../../media/', '/media/bookmarks/')

                with open(html_file, "w", encoding="utf-8") as f:
                    f.write(content)

    # Copy timeline from master (already generated with correct structure)
    src_timeline = MASTER_HTML_DIR / "timeline"
    if src_timeline.exists():
        print("Copying timeline pages...")
        import shutil as sh
        dst_timeline = html_dir / "timeline"
        if dst_timeline.exists():
            sh.rmtree(dst_timeline)
        sh.copytree(src_timeline, dst_timeline)

        # Fix paths in timeline files
        for html_file in dst_timeline.glob("**/*.html"):
            with open(html_file, "r", encoding="utf-8") as f:
                content = f.read()

            content = fix_paths_for_server(content)
            content = add_newgen_link(content)
            # Fix media paths
            content = content.replace('../../media/', '/media/bookmarks/')
            content = content.replace('../../../media/', '/media/bookmarks/')
            content = content.replace('../../../../media/', '/media/bookmarks/')

            with open(html_file, "w", encoding="utf-8") as f:
                f.write(content)

    # Copy authors from master (already generated with correct structure)
    src_authors = MASTER_HTML_DIR / "authors"
    if src_authors.exists():
        print("Copying authors pages...")
        import shutil as sh
        dst_authors = html_dir / "authors"
        if dst_authors.exists():
            sh.rmtree(dst_authors)
        sh.copytree(src_authors, dst_authors)

        # Fix paths in authors files
        for html_file in dst_authors.glob("**/*.html"):
            with open(html_file, "r", encoding="utf-8") as f:
                content = f.read()

            content = fix_paths_for_server(content)
            content = add_newgen_link(content)
            # Fix media paths
            content = content.replace('../../media/', '/media/bookmarks/')

            with open(html_file, "w", encoding="utf-8") as f:
                f.write(content)

    print(f"Generated server HTML in {html_dir}")


# Output directory for server HTML (can be synced to server)
SERVER_HTML_DIR = BASE_DIR / "server" / "html"


def cmd_publish_server(args: argparse.Namespace) -> None:
    """Generate HTML for server deployment (to be synced via rsync)"""

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

    print("=== Generating HTML for Server Deployment ===")

    # Create server output directory
    server_dir = BASE_DIR / "server"
    server_dir.mkdir(exist_ok=True)

    # Generate HTML with server media paths
    generate_html_server(server_dir, bookmarks, categories_data, stories_data)

    print(f"\n✓ Generated server HTML in {SERVER_HTML_DIR}")
    print(f"\nTo deploy, sync to server:")
    print(f"  rsync -avz --delete {SERVER_HTML_DIR}/ user@server:/app/bookmarks-html/")
    print(f"  rsync -avz --progress {MASTER_MEDIA_DIR}/ user@server:/app/bookmarks-media/")


def cmd_thumbnails(args: argparse.Namespace) -> None:
    """Generate video thumbnails for all videos in master/media"""
    print("=== Generating Video Thumbnails ===")

    if not MASTER_MEDIA_DIR.exists():
        print(f"Media directory not found: {MASTER_MEDIA_DIR}")
        print("Run 'consolidate' first to collect media files.")
        return

    count = generate_video_thumbnails(MASTER_MEDIA_DIR)
    if count > 0:
        print(f"\n✓ Generated {count} new thumbnails")
        print("\nRun 'generate' and 'publish-server' to update HTML with poster images.")
    else:
        print("\n✓ All thumbnails already exist (or no videos found)")


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

    # Authors command with subcommands
    authors_parser = subparsers.add_parser("authors", help="Manage author profiles and AI categorization")
    authors_parser.add_argument("authors_command", nargs="?", choices=["categorize", "generate"], help="Subcommand (default: both)")
    authors_parser.add_argument("--min-bookmarks", type=int, default=3, help="Minimum bookmarks for AI categorization (default: 3)")

    # Publish commands
    subparsers.add_parser("publish", help="Publish to GitHub Pages (dethele.com/twitter) using Twitter CDN")
    subparsers.add_parser("unpublish", help="Remove from GitHub Pages (DESTRUCTIVE)")
    subparsers.add_parser("publish-server", help="Generate HTML for server deployment (twitter.dethele.com)")
    subparsers.add_parser("thumbnails", help="Generate video thumbnails (requires ffmpeg)")

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
        "authors": cmd_authors,
        "publish": cmd_publish,
        "unpublish": cmd_unpublish,
        "publish-server": cmd_publish_server,
        "thumbnails": cmd_thumbnails,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
