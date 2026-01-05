#!/usr/bin/env python3
"""
Twitter Bookmarks Merger Tool

Merge multiple X/Twitter bookmark exports, deduplicate, generate HTML views,
categorize with AI, and export for NotebookLM.

Usage:
    python bookmark_merger.py merge       # Deduplicate JSON files
    python bookmark_merger.py consolidate # Consolidate media files
    python bookmark_merger.py categorize  # AI categorization
    python bookmark_merger.py generate    # Generate HTML pages
    python bookmark_merger.py export      # Export for NotebookLM
    python bookmark_merger.py all         # Run merge, consolidate, generate, export
    python bookmark_merger.py clean       # Delete generated files to re-run
    python bookmark_merger.py cleanup-raw # Delete raw exports (DESTRUCTIVE)
"""

import argparse
import json
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

    # Sort by created date (newest first)
    deduped.sort(key=lambda x: x.get("Created At", ""), reverse=True)

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

    for cat_id, tweet_ids in category_tweets.items():
        if not tweet_ids:
            continue

        # Get tweets for this category
        cat_tweets = [tweet_lookup.get(tid) for tid in tweet_ids if tid in tweet_lookup]
        cat_tweets = [t for t in cat_tweets if t]

        if not cat_tweets:
            continue

        # Group by time periods
        by_period: dict[str, list[dict]] = defaultdict(list)
        for tweet in cat_tweets:
            dt = parse_tweet_date(tweet.get("Created At", ""))
            if dt:
                periods = get_time_periods(dt)
                by_period[periods["year"]].append(tweet)
                by_period[periods["month"]].append(tweet)

        # Generate summary for each period with enough tweets
        for period, period_tweets in by_period.items():
            if len(period_tweets) < 3:
                continue

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
        nav {{ margin-bottom: 20px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }}
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
        .hidden {{ display: none; }}
    </style>
</head>
<body>
    <nav>
        <a href="../index.html">Chronological</a>
        <a href="../categories/index.html">Categories</a>
        <a href="../timeline/index.html">Timeline</a>
    </nav>
    {content}
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
    """Render HTML for tweet media"""
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


def render_tweet_card(bookmark: dict, categories_data: dict | None = None,
                      include_detail_link: bool = True) -> str:
    """Render a tweet card HTML"""
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

    return TWEET_TEMPLATE.format(
        tweet_id=tweet_id,
        avatar_url=bookmark.get("User Avatar Url", ""),
        name=bookmark.get("User Name", "Unknown"),
        screen_name=bookmark.get("User Screen Name", "unknown"),
        text=bookmark.get("Full Text", ""),
        media_html=render_media_html(tweet_id, MASTER_MEDIA_DIR),
        categories_html=categories_html,
        likes=bookmark.get("Favorite Count", 0),
        retweets=bookmark.get("Retweet Count", 0),
        replies=bookmark.get("Reply Count", 0),
        date=formatted_date,
        detail_link=detail_link,
        search_text=bookmark.get("Full Text", "").lower().replace('"', '&quot;')[:500]
    )


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

    # Generate main index (chronological)
    print("Generating main index...")
    index_content = """
<h1>Twitter Bookmarks</h1>
<p class="meta">{count} bookmarks</p>
<input type="text" class="search-box" placeholder="Search tweets..." oninput="filterTweets(this.value)">
<div id="tweets-container">
{tweets}
</div>
<script>
function filterTweets(query) {{
    query = query.toLowerCase();
    document.querySelectorAll('.tweet-card').forEach(card => {{
        const text = card.dataset.text || '';
        card.classList.toggle('hidden', query && !text.includes(query));
    }});
}}
</script>
""".format(
        count=len(bookmarks),
        tweets="\n".join(render_tweet_card(b, categories_data) for b in bookmarks)
    )

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

        # Category index
        cat_index_content = "<h1>Categories</h1>\n"
        for cat_id, cat_info in sorted(categories.items(), key=lambda x: len(x[1].get("tweet_ids", [])), reverse=True):
            tweet_count = len(cat_info.get("tweet_ids", []))
            cat_index_content += f"""
<div class="tweet-card">
    <h3><a href="{cat_id}.html">{cat_info.get('name', cat_id)}</a></h3>
    <p>{cat_info.get('description', '')}</p>
    <p class="meta">{tweet_count} bookmarks</p>
</div>
"""

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

            cat_content = f"""
<h1>{cat_info.get('name', cat_id)}</h1>
<p class="meta">{len(cat_tweets)} bookmarks</p>
{summary_html}
<div id="tweets-container">
{"".join(render_tweet_card(t, categories_data) for t in cat_tweets)}
</div>
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


def cmd_all(args: argparse.Namespace) -> None:
    """Run merge, consolidate, generate, and export"""
    cmd_merge(args)
    print()
    cmd_consolidate(args)
    print()
    cmd_generate(args)
    print()
    cmd_export(args)


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
    subparsers.add_parser("clean", help="Delete generated files (master/) to re-run")
    subparsers.add_parser("cleanup-raw", help="Delete raw exports (DESTRUCTIVE)")
    subparsers.add_parser("all", help="Run merge, consolidate, generate, export")

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
        "clean": cmd_clean,
        "cleanup-raw": cmd_cleanup_raw,
        "all": cmd_all,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
