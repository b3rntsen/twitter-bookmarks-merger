#!/usr/bin/env python3
"""
Convert cached markdown files from birdmarks_cache to JSON without fetching new ones.
"""

import sys
from pathlib import Path
from datetime import datetime
import json

# Add tools directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from birdmarks_bridge import (
    convert_all_bookmarks,
    load_existing_tweet_ids,
    get_last_sync_date,
    parse_twitter_date,
    BIRDMARKS_CACHE,
    OUTPUT_DIR
)

def main():
    print("🔄 Converting Cached Bookmarks")
    print("=" * 50)

    # Check if cache exists
    if not BIRDMARKS_CACHE.exists():
        print("❌ No cache directory found")
        return

    md_files = list(BIRDMARKS_CACHE.glob("*.md"))
    if not md_files:
        print("⚠️  No markdown files to convert")
        return

    print(f"📄 Found {len(md_files)} markdown files to convert")

    # Load existing bookmarks for deduplication
    print("📊 Loading existing bookmarks...")
    existing_ids = load_existing_tweet_ids()
    last_sync_date = get_last_sync_date()

    print(f"   Existing: {len(existing_ids)} bookmarks")
    if last_sync_date:
        print(f"   Last sync: {last_sync_date[:19]}")

    # Convert - don't use stop_before date since "Created At" is when tweet was posted,
    # not when it was bookmarked. Just rely on duplicate detection.
    print("\n🔄 Converting markdown to JSON...")
    bookmarks, stopped_early = convert_all_bookmarks(
        BIRDMARKS_CACHE,
        existing_ids,
        stop_before_date=None,  # Don't stop on old tweets - they might still be newly bookmarked
        keep_cache=True  # Keep markdown files after conversion
    )

    if not bookmarks:
        print("\n⚠️  No new bookmarks found (all duplicates or too old)")
        return

    # Save to JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"birdmarks-{datetime.now().strftime('%Y-%m-%d')}.json"

    # If file exists, merge with existing
    if output_file.exists():
        print(f"\n📝 Merging with existing {output_file.name}")
        with open(output_file, 'r', encoding='utf-8') as f:
            existing_bookmarks = json.load(f)

        # Merge (new bookmarks first)
        all_bookmarks = bookmarks + existing_bookmarks

        # Deduplicate by Tweet Id
        seen_ids = set()
        unique_bookmarks = []
        for bookmark in all_bookmarks:
            tweet_id = bookmark.get("Tweet Id")
            if tweet_id and tweet_id not in seen_ids:
                seen_ids.add(tweet_id)
                unique_bookmarks.append(bookmark)

        print(f"   Before merge: {len(existing_bookmarks)} bookmarks")
        print(f"   Adding: {len(bookmarks)} new bookmarks")
        print(f"   After dedupe: {len(unique_bookmarks)} unique bookmarks")

        bookmarks = unique_bookmarks

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(bookmarks, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Saved to {output_file}")
    print(f"\n✅ Done! Converted {len(bookmarks)} total bookmarks")
    print(f"\nNext step: python3 tools/bookmark_merger.py update")

if __name__ == "__main__":
    main()
