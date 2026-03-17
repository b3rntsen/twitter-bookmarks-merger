"""Shared markdown parsing utilities for birdmarks content.

Used by both birdmarks_bridge.py (CLI tool) and web/twitter/tasks.py (Django).
"""

import re
from pathlib import Path


def parse_frontmatter(content: str) -> tuple:
    """Parse YAML frontmatter from markdown content.

    Returns:
        tuple: (frontmatter_dict, body_str)
    """
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


def extract_media_filenames(body: str) -> list[str]:
    """Extract media filenames from markdown body.

    Finds all ![](assets/filename.ext) patterns.

    Returns:
        list of filenames (without assets/ prefix)
    """
    pattern = r'!\[\]\(assets/([^)]+)\)'
    return re.findall(pattern, body)


def classify_media_type(filename: str) -> str:
    """Classify a media file as 'video' or 'photo'/'image' based on extension.

    Returns 'video' for video files, 'photo' otherwise.
    """
    ext = Path(filename).suffix.lower()
    if ext in ['.mp4', '.webm', '.mov', '.m4v']:
        return 'video'
    return 'photo'
