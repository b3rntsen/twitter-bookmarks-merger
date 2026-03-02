#!/usr/bin/env python3
"""
Birdmarks Bridge - Fetch Twitter bookmarks via birdmarks and convert to XBookmarksExporter format.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SECRETS_FILE = Path.home() / ".openclaw" / "secrets" / "twitter-cookies.json"
BIRDMARKS_DIR = Path(__file__).parent.parent.parent / "birdmarks"  # Sibling folder
BIRDMARKS_BIN = BIRDMARKS_DIR / "birdmarks"  # Precompiled binary
OUTPUT_DIR = Path(__file__).parent.parent / "raw" / "json"
BIRDMARKS_CACHE = Path(__file__).parent.parent / "birdmarks_cache"  # Persistent cache for state


def check_birdmarks_state() -> dict | None:
    """Check if birdmarks has saved state for resumption."""
    state_file = BIRDMARKS_CACHE / "exporter-state.json"
    if not state_file.exists():
        return None

    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Warning: Could not read state file: {e}")
        return None


def load_existing_tweet_ids() -> set[str]:
    """Load all existing Tweet IDs from raw/json/ directory for deduplication."""
    existing_ids = set()

    if not OUTPUT_DIR.exists():
        return existing_ids

    for json_file in OUTPUT_DIR.glob("*.json"):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                bookmarks = json.load(f)
                for bookmark in bookmarks:
                    tweet_id = bookmark.get("Tweet Id")
                    if tweet_id:
                        existing_ids.add(str(tweet_id))
        except Exception as e:
            print(f"⚠️  Warning: Could not read {json_file.name}: {e}")
            continue

    return existing_ids


def get_last_sync_date() -> str | None:
    """Get the most recent Scraped At timestamp from existing bookmarks."""
    if not OUTPUT_DIR.exists():
        return None

    all_scraped_times = []

    for json_file in OUTPUT_DIR.glob("*.json"):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                bookmarks = json.load(f)
                for bookmark in bookmarks:
                    scraped_at = bookmark.get("Scraped At")
                    if scraped_at:
                        all_scraped_times.append(scraped_at)
        except Exception as e:
            print(f"⚠️  Warning: Could not read {json_file.name}: {e}")
            continue

    return max(all_scraped_times) if all_scraped_times else None


def parse_twitter_date(date_str: str) -> datetime:
    """Parse Twitter's date format: 'Sat Feb 28 12:34:56 +0000 2026'"""
    from datetime import timezone
    if not date_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        # Twitter format: "Sat Feb 28 12:34:56 +0000 2026"
        return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        # Fallback: Try ISO format
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except:
            return datetime.min.replace(tzinfo=timezone.utc)


def load_cookies():
    if not SECRETS_FILE.exists():
        print(f"❌ Cookies file not found: {SECRETS_FILE}")
        sys.exit(1)
    
    with open(SECRETS_FILE) as f:
        cookies = json.load(f)
    
    if "auth_token" not in cookies or "ct0" not in cookies:
        print(f"❌ Missing auth_token or ct0 in {SECRETS_FILE}")
        sys.exit(1)
    
    return cookies


def parse_frontmatter(content: str) -> tuple:
    if not content.startswith("---"):
        return {}, content
    
    end_idx = content.find("\n---", 3)
    if end_idx == -1:
        return {}, content
    
    frontmatter_str = content[4:end_idx]
    body = content[end_idx + 4:].strip()
    
    frontmatter = {}
    current_key = None
    current_array = None
    
    for line in frontmatter_str.split("\n"):
        if line.startswith("  - ") and current_key and current_array is not None:
            current_array.append(line[4:].strip())
            continue
        
        match = re.match(r'^(\w+):\s*(.*)$', line)
        if match:
            if current_key and current_array is not None:
                frontmatter[current_key] = current_array
            
            current_key = match.group(1)
            value = match.group(2).strip()
            
            if value == "":
                current_array = []
            else:
                current_array = None
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    frontmatter[current_key] = value[1:-1]
                elif value.isdigit():
                    frontmatter[current_key] = int(value)
                else:
                    frontmatter[current_key] = value
    
    if current_key and current_array is not None:
        frontmatter[current_key] = current_array
    
    return frontmatter, body


def extract_tweet_text(body: str) -> str:
    """Extract the actual tweet text from markdown body."""
    lines = body.split('\n')
    text_lines = []
    skip_header = True
    
    for line in lines:
        # Skip the header section (# Thread, author line, date, View on Twitter link)
        if skip_header:
            if line.startswith('# ') or line.startswith('**@') or re.match(r'^\d{4}-\d{2}-\d{2}$', line.strip()):
                continue
            if '[View on Twitter]' in line or line.strip() == '':
                continue
            skip_header = False
        
        # Stop at thread/reply separators
        if line.strip() == '---' or line.startswith('## '):
            break
        
        # Skip image embeds
        if line.startswith('!['):
            continue
        
        text_lines.append(line)
    
    text = '\n'.join(text_lines).strip()
    # Clean up markdown links [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Clean up bold/italic
    text = re.sub(r'\*+([^*]+)\*+', r'\1', text)
    return text


def convert_bookmark(md_file: Path) -> dict:
    try:
        content = md_file.read_text(encoding='utf-8')
    except Exception as e:
        print(f"   ⚠ Failed to read {md_file}: {e}")
        return None
    
    frontmatter, body = parse_frontmatter(content)
    
    if not frontmatter.get("id"):
        return None
    
    full_text = extract_tweet_text(body)
    
    date_str = frontmatter.get("date", "")
    try:
        from datetime import timezone
        if date_str:
            dt = datetime.fromisoformat(str(date_str))
            # Ensure timezone-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.now(timezone.utc)
        created_at = dt.strftime("%a %b %d %H:%M:%S +0000 %Y")
    except:
        created_at = str(date_str)
    
    return {
        "Tweet Id": str(frontmatter.get("id", "")),
        "Full Text": full_text,
        "Created At": created_at,
        "Scraped At": datetime.now().isoformat(),
        "Tweet URL": frontmatter.get("url", ""),
        "User Screen Name": frontmatter.get("author", ""),
        "User Name": frontmatter.get("author_name", ""),
        "User Avatar Url": "",
        "User Description": "",
        "User Location": "",
        "User Followers Count": "",
        "User Is Blue Verified": "",
        "Retweet Count": "",
        "Reply Count": str(frontmatter.get("reply_count", "")),
        "Favorite Count": "",
        "Media URLs": "",
        "Media Types": "",
    }


def run_birdmarks(output_dir: Path, max_pages: int, dry_run: bool, until_synced: bool = False) -> bool:
    """Run birdmarks binary with optional rebuild mode for gap-free sync."""
    cookies = load_cookies()

    if dry_run:
        mode = "rebuild (until synced)" if until_synced else f"{max_pages} pages"
        print(f"🔍 DRY RUN - Would fetch ({mode})")
        print(f"   Auth token: {cookies['auth_token'][:10]}...")
        return True

    output_dir.mkdir(parents=True, exist_ok=True)

    if not BIRDMARKS_BIN.exists():
        print(f"❌ Birdmarks binary not found: {BIRDMARKS_BIN}")
        return False

    cmd = [str(BIRDMARKS_BIN), str(output_dir)]

    # Use rebuild mode for until-synced (iterates from beginning, smart stops)
    if until_synced:
        cmd.append("--rebuild")
        print(f"📥 Fetching bookmarks (rebuild mode - will stop at existing)...")
    else:
        cmd.extend(["--max-pages", str(max_pages)])
        print(f"📥 Fetching bookmarks (max {max_pages} pages, ~{max_pages * 40} bookmarks)...")

    env = os.environ.copy()
    env["AUTH_TOKEN"] = cookies["auth_token"]
    env["CT0"] = cookies["ct0"]

    try:
        # Stream output in real-time to show progress
        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        exported_count = 0
        processing_count = 0

        # Read output line by line
        for line in process.stdout:
            print(line, end='')  # Print original line

            # Parse progress indicators
            if "Processing bookmark" in line:
                # Extract current count from "Processing bookmark X/Y..."
                match = re.search(r'Processing bookmark (\d+)/(\d+)', line)
                if match:
                    processing_count = int(match.group(1))
                    total = int(match.group(2))
                    if processing_count % 10 == 0:  # Show every 10th bookmark
                        print(f"   📊 Progress: {processing_count}/{total} bookmarks processed")

            # Extract final export count
            if "Exported:" in line:
                match = re.search(r'Exported:\s*(\d+)', line)
                if match:
                    exported_count = int(match.group(1))

        # Wait for process to complete
        stderr_output = process.stderr.read()
        returncode = process.wait(timeout=300)

        if returncode != 0:
            print(f"❌ Birdmarks failed: {stderr_output}")
            return False

        # Show final count
        if exported_count > 0:
            print(f"   ✅ Exported {exported_count} new bookmarks")

        return True
    except subprocess.TimeoutExpired:
        process.kill()
        print(f"❌ Timeout after 300 seconds")
        return False
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False


def convert_all_bookmarks(
    birdmarks_output: Path,
    existing_ids: set[str],
    stop_before_date: datetime | None,
    keep_cache: bool = False
) -> tuple[list, bool]:
    """
    Convert markdown bookmarks to JSON format with smart stopping.

    Args:
        birdmarks_output: Directory containing markdown files
        existing_ids: Set of already-fetched tweet IDs
        stop_before_date: Stop when reaching tweets older than this
        keep_cache: If True, preserve markdown files and state file

    Returns:
        tuple: (bookmarks, stopped_early)
    """
    bookmarks = []
    stopped_early = False
    skipped_count = 0

    md_files = list(birdmarks_output.rglob("*.md"))
    print(f"📄 Found {len(md_files)} markdown files")

    for md_file in md_files:
        bookmark = convert_bookmark(md_file)
        if not bookmark:
            continue

        tweet_id = bookmark.get("Tweet Id")

        # Skip if already exists
        if tweet_id and tweet_id in existing_ids:
            skipped_count += 1
            if skipped_count <= 3:  # Only print first few to avoid spam
                print(f"   ⏭️  Skipping duplicate: {tweet_id}")
            continue

        # Check if too old (stop if before threshold)
        if stop_before_date:
            created_at_str = bookmark.get("Created At", "")
            created_at = parse_twitter_date(created_at_str)

            try:
                # Make both timezone-aware if needed for comparison
                from datetime import timezone
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                if stop_before_date.tzinfo is None:
                    stop_before_date = stop_before_date.replace(tzinfo=timezone.utc)

                if created_at < stop_before_date:
                    print(f"   🛑 Stopped at old bookmark: {tweet_id} (created {created_at_str[:16]})")
                    stopped_early = True
                    break
            except (TypeError, AttributeError):
                # If comparison fails, skip this check and continue
                pass

        bookmarks.append(bookmark)

    if skipped_count > 3:
        print(f"   ⏭️  Skipped {skipped_count} duplicates total")

    # Clean up markdown files if not keeping cache
    if not keep_cache:
        for md_file in md_files:
            try:
                md_file.unlink()
            except:
                pass  # Ignore cleanup errors

    print(f"✅ Converted {len(bookmarks)} NEW bookmarks")
    return bookmarks, stopped_early


def main():
    parser = argparse.ArgumentParser(description="Fetch Twitter bookmarks via birdmarks")
    parser.add_argument("--max-pages", type=int, default=2, help="Max pages (default: 2, ~80 bookmarks)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without fetching")
    parser.add_argument("--stop-before", type=str, help="Stop at bookmarks created before this date (YYYY-MM-DD)")
    parser.add_argument("--until-synced", action="store_true",
                       help="Keep fetching until reaching last synced bookmark (may take multiple runs)")
    args = parser.parse_args()

    print("🐦 Birdmarks Bridge")
    print("=" * 40)

    # Load existing data for smart stopping
    print("📊 Checking existing bookmarks...")
    existing_ids = load_existing_tweet_ids()
    last_sync_date = get_last_sync_date()

    print(f"   Found {len(existing_ids)} existing bookmarks")
    if last_sync_date:
        print(f"   Last sync: {last_sync_date[:19]}")
    else:
        print(f"   No previous sync found - will fetch all")

    # Check saved state for resumption
    state = check_birdmarks_state()
    if state:
        if state.get("allBookmarksProcessed"):
            print(f"   ✅ All bookmarks already fetched")
        elif state.get("nextCursor"):
            print(f"   📍 Resuming from saved cursor")
            # Show progress if available
            total_exported = state.get("totalExported", 0)
            if total_exported > 0:
                print(f"   📊 Cumulative progress: {total_exported} bookmarks exported across all runs")
        else:
            print(f"   🆕 Starting fresh (no saved cursor)")

    # Determine stop date
    if args.stop_before:
        stop_before = datetime.strptime(args.stop_before, "%Y-%m-%d").replace(tzinfo=None)
        print(f"   Stop before: {args.stop_before} (manual override)")
    elif last_sync_date:
        stop_before = datetime.fromisoformat(last_sync_date.replace('Z', '+00:00'))
    else:
        stop_before = None

    # Use persistent cache for state preservation
    birdmarks_output = BIRDMARKS_CACHE
    birdmarks_output.mkdir(parents=True, exist_ok=True)

    if not run_birdmarks(birdmarks_output, args.max_pages, args.dry_run, args.until_synced):
        sys.exit(1)

    if args.dry_run:
        return

    # Convert with keep_cache=True to preserve state file
    bookmarks, stopped_early = convert_all_bookmarks(
        birdmarks_output,
        existing_ids,
        stop_before,
        keep_cache=True
    )

    if not bookmarks:
        print("⚠️  No new bookmarks found")
        # Check updated state after this run
        state = check_birdmarks_state()
        if state:
            if state.get("allBookmarksProcessed"):
                print("   ✅ Gap filled! All bookmarks synced.")
            elif args.until_synced and state.get("nextCursor"):
                print("   💡 Tip: Run again to resume after rate limit")
                if "totalExported" in state:
                    print(f"   Progress: {state.get('totalExported', 0)} bookmarks exported so far")
        return

    if stopped_early:
        print(f"🛑 Stopped early (reached existing/old bookmarks)")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"birdmarks-{datetime.now().strftime('%Y-%m-%d')}.json"

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(bookmarks, f, indent=2, ensure_ascii=False)

    print(f"💾 Saved to {output_file}")

    # Show status summary
    print(f"📈 Summary:")
    print(f"   New bookmarks this run: {len(bookmarks)}")
    print(f"   Total existing bookmarks: {len(existing_ids)}")
    print(f"   Total after merge: {len(existing_ids) + len(bookmarks)}")

    # Check if gap is filled
    state = check_birdmarks_state()
    if state and state.get("allBookmarksProcessed"):
        print(f"   ✅ Gap filled! All bookmarks synced.")


if __name__ == "__main__":
    main()
