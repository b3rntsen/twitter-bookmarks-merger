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
BIRDMARKS_DIR = Path.home() / "projects" / "birdmarks"
BUN_PATH = Path.home() / ".nix-profile" / "bin" / "bun"
OUTPUT_DIR = Path(__file__).parent.parent / "raw" / "json"


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
        dt = datetime.fromisoformat(str(date_str)) if date_str else datetime.now()
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


def run_birdmarks(output_dir: Path, max_pages: int, dry_run: bool) -> bool:
    cookies = load_cookies()
    
    if dry_run:
        print(f"🔍 DRY RUN - Would fetch {max_pages} pages")
        print(f"   Auth token: {cookies['auth_token'][:10]}...")
        return True
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        str(BUN_PATH), "run", str(BIRDMARKS_DIR / "src" / "index.ts"),
        str(output_dir), "--max-pages", str(max_pages),
    ]
    
    env = os.environ.copy()
    env["AUTH_TOKEN"] = cookies["auth_token"]
    env["CT0"] = cookies["ct0"]
    
    print(f"📥 Fetching bookmarks (max {max_pages} pages, ~{max_pages * 40} bookmarks)...")
    
    try:
        result = subprocess.run(cmd, env=env, cwd=BIRDMARKS_DIR, capture_output=True, text=True, timeout=300)
        print(result.stdout)
        if result.returncode != 0:
            print(f"❌ Birdmarks failed: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False


def convert_all_bookmarks(birdmarks_output: Path) -> list:
    bookmarks = []
    md_files = list(birdmarks_output.rglob("*.md"))
    print(f"📄 Found {len(md_files)} markdown files")
    
    for md_file in md_files:
        bookmark = convert_bookmark(md_file)
        if bookmark:
            bookmarks.append(bookmark)
    
    print(f"✅ Converted {len(bookmarks)} bookmarks")
    return bookmarks


def main():
    parser = argparse.ArgumentParser(description="Fetch Twitter bookmarks via birdmarks")
    parser.add_argument("--max-pages", type=int, default=2, help="Max pages (default: 2, ~80 bookmarks)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without fetching")
    args = parser.parse_args()
    
    print("🐦 Birdmarks Bridge")
    print("=" * 40)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        birdmarks_output = Path(tmpdir)
        
        if not run_birdmarks(birdmarks_output, args.max_pages, args.dry_run):
            sys.exit(1)
        
        if args.dry_run:
            return
        
        bookmarks = convert_all_bookmarks(birdmarks_output)
        
        if not bookmarks:
            print("⚠ No bookmarks to save")
            return
        
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_file = OUTPUT_DIR / f"birdmarks-{datetime.now().strftime('%Y-%m-%d')}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(bookmarks, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Saved to {output_file}")


if __name__ == "__main__":
    main()
