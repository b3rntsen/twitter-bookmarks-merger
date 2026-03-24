"""Django-Q tasks for bookmark synchronization."""
import subprocess
import sys
import re
import json
import os
import logging
from pathlib import Path
from datetime import timedelta, datetime, timezone as dt_timezone
from django.utils import timezone
from django_q.tasks import schedule as q_schedule
from django_q.models import Schedule as DjangoQSchedule
from .models import TwitterProfile, BookmarkSyncJob, BookmarkSyncSchedule, Tweet, TweetMedia

# Shared markdown parsing (from tools/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'tools'))
from markdown_parser import parse_frontmatter, extract_tweet_text, extract_media_filenames, classify_media_type

logger = logging.getLogger(__name__)

# Path to master data on server (rsynced from local)
MASTER_DIR = Path(__file__).parent.parent.parent / 'master'
TOOLS_DIR = Path(__file__).parent.parent.parent / 'tools'
SERVER_HTML_DIR = Path(__file__).parent.parent.parent / 'server' / 'html'
BOOKMARKS_HTML_DIR = Path(__file__).parent.parent.parent / 'bookmarks-html'
BIRDMARKS_CACHE = Path(__file__).parent.parent.parent / 'birdmarks_cache'
BOOKMARKS_MEDIA_DIR = Path(os.environ.get('BOOKMARKS_MEDIA_DIR',
                                           str(MASTER_DIR / 'media')))


def sync_all_media(cache_dir: Path) -> int:
    """Copy ALL media from birdmarks markdown files to bookmarks-media/{tweet_id}/.

    Parses every .md file in cache_dir, not just new tweets. Idempotent - skips
    files that already exist at the destination with the same size.
    """
    import shutil
    copied = 0
    for md_file in cache_dir.glob('*.md'):
        try:
            content = md_file.read_text(encoding='utf-8')
            frontmatter, body = parse_frontmatter(content)
            tweet_id = str(frontmatter.get('id', ''))
            if not tweet_id:
                continue

            filenames = extract_media_filenames(body)
            if not filenames:
                continue

            tweet_dir = BOOKMARKS_MEDIA_DIR / tweet_id
            for filename in filenames:
                src = cache_dir / 'assets' / filename
                if not src.exists():
                    continue
                dest = tweet_dir / filename
                if dest.exists() and dest.stat().st_size == src.stat().st_size:
                    continue
                tweet_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                copied += 1
        except Exception as e:
            logger.warning(f"sync_all_media: error processing {md_file.name}: {e}")
            continue

    if copied:
        logger.info(f"sync_all_media: copied {copied} media files to {BOOKMARKS_MEDIA_DIR}")
    return copied


def categorize_uncategorized_tweets(max_per_cycle: int = 100) -> int:
    """Categorize tweets that are in bookmarks.json but not in categories.json.

    Uses the Anthropic API with existing categories as context.
    Returns count of newly categorized tweets.
    """
    from collections import defaultdict

    categories_file = MASTER_DIR / 'categories.json'
    bookmarks_file = MASTER_DIR / 'bookmarks.json'

    if not bookmarks_file.exists():
        return 0

    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        logger.info("categorize_uncategorized_tweets: ANTHROPIC_API_KEY not set, skipping")
        return 0

    try:
        import anthropic
    except ImportError:
        logger.warning("categorize_uncategorized_tweets: anthropic package not installed")
        return 0

    # Load data
    with open(bookmarks_file, 'r', encoding='utf-8') as f:
        bookmarks = json.load(f)

    existing_categories = {"categories": {}, "tweet_categories": {}}
    if categories_file.exists():
        with open(categories_file, 'r', encoding='utf-8') as f:
            existing_categories = json.load(f)

    # Find uncategorized tweet IDs
    tweet_categories = existing_categories.get("tweet_categories", {})
    uncategorized = [b for b in bookmarks if b["Tweet Id"] not in tweet_categories]
    if not uncategorized:
        return 0

    uncategorized = uncategorized[:max_per_cycle]
    logger.info(f"categorize_uncategorized_tweets: {len(uncategorized)} tweets to categorize")

    client = anthropic.Anthropic(api_key=api_key)
    existing_cat_info = existing_categories.get("categories", {})
    all_cat_list = ", ".join(existing_cat_info.keys())

    if not all_cat_list:
        logger.warning("categorize_uncategorized_tweets: no existing categories, skipping")
        return 0

    # Rebuild category_tweets index
    category_tweets = defaultdict(list)
    for cat_id, cat_info in existing_cat_info.items():
        if "tweet_ids" in cat_info:
            category_tweets[cat_id] = list(cat_info["tweet_ids"])

    categorized_count = 0
    batch_size = 20
    for i in range(0, len(uncategorized), batch_size):
        batch = uncategorized[i:i + batch_size]
        batch_prompt = f"""Categorize these tweets. Available categories: {all_cat_list}

Assign 1-3 categories to each tweet. Return JSON only:
{{"tweet_id": ["category1", "category2"]}}

Tweets:
"""
        for b in batch:
            batch_prompt += f'\n{b.get("Tweet Id")}: {b.get("Full Text", "")[:300]}'

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[{"role": "user", "content": batch_prompt}]
            )
            result_text = response.content[0].text
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]
            batch_results = json.loads(result_text)

            for tid, cats in batch_results.items():
                tweet_categories[tid] = cats
                for cat in cats:
                    if cat in existing_cat_info and tid not in category_tweets[cat]:
                        category_tweets[cat].append(tid)
                categorized_count += 1
        except Exception as e:
            logger.warning(f"categorize_uncategorized_tweets: batch error: {e}")
            continue

    # Save updated categories
    final_categories = {
        "categories": {},
        "tweet_categories": dict(tweet_categories)
    }
    for cat_id, cat_info in existing_cat_info.items():
        final_categories["categories"][cat_id] = {
            "name": cat_info.get("name", cat_id),
            "description": cat_info.get("description", ""),
            "tweet_ids": category_tweets.get(cat_id, []),
            "summaries": cat_info.get("summaries", {})
        }

    categories_file.parent.mkdir(parents=True, exist_ok=True)
    with open(categories_file, 'w', encoding='utf-8') as f:
        json.dump(final_categories, f, indent=2, ensure_ascii=False)

    logger.info(f"categorize_uncategorized_tweets: categorized {categorized_count} tweets")
    return categorized_count


def import_tweet_media(tweet: Tweet, markdown_body: str, cache_dir: Path) -> int:
    """Extract media from birdmarks markdown and create TweetMedia records.

    Args:
        tweet: Saved Tweet instance
        markdown_body: Markdown with ![](assets/file.jpg) references
        cache_dir: birdmarks_cache directory with assets/ folder

    Returns:
        Count of media files imported
    """
    import shutil
    from django.conf import settings

    filenames = extract_media_filenames(markdown_body)
    if not filenames:
        return 0

    # Create Django media directory
    tweet_media_dir = Path(settings.MEDIA_ROOT) / 'tweets' / str(tweet.tweet_id)
    tweet_media_dir.mkdir(parents=True, exist_ok=True)

    # Also create bookmarks media directory (for static site)
    bookmarks_media_dir = Path('/app/bookmarks-media') / str(tweet.tweet_id)
    bookmarks_media_dir.mkdir(parents=True, exist_ok=True)

    media_count = 0
    for filename in filenames:
        source = cache_dir / 'assets' / filename
        if not source.exists():
            logger.warning(f"Media not found: {source}")
            continue

        # classify_media_type returns 'photo'/'video'; Django uses 'image'/'video'
        raw_type = classify_media_type(filename)
        media_type = 'image' if raw_type == 'photo' else raw_type

        # Copy to Django media and bookmarks media
        dest = tweet_media_dir / filename
        bookmarks_dest = bookmarks_media_dir / filename
        try:
            shutil.copy2(source, dest)
            shutil.copy2(source, bookmarks_dest)
            file_size = dest.stat().st_size

            # Generate video thumbnail
            thumbnail_rel = ''
            if media_type == 'video':
                thumbnail_rel = generate_video_thumbnail(dest, tweet_media_dir, tweet.tweet_id)

            # Create TweetMedia record
            TweetMedia.objects.create(
                tweet=tweet,
                media_type=media_type,
                file_path=f"tweets/{tweet.tweet_id}/{filename}",
                original_url=f"birdmarks://assets/{filename}",
                thumbnail_path=thumbnail_rel or '',
                file_size=file_size
            )
            media_count += 1
            logger.debug(f"  Imported media: {filename} ({file_size} bytes)")

        except Exception as e:
            logger.error(f"Failed to copy media {filename}: {e}")
            continue

    return media_count


def generate_video_thumbnail(video_path: Path, output_dir: Path, tweet_id: str) -> str:
    """Generate thumbnail with ffmpeg.

    Args:
        video_path: Path to video file
        output_dir: Directory to save thumbnail
        tweet_id: Tweet ID for path construction

    Returns:
        Relative path from MEDIA_ROOT to thumbnail, or empty string if failed
    """
    thumb_name = f"thumb_{video_path.stem}.jpg"
    thumb_path = output_dir / thumb_name

    try:
        subprocess.run([
            'ffmpeg', '-i', str(video_path), '-ss', '00:00:01',
            '-vframes', '1', '-q:v', '2', str(thumb_path),
            '-y', '-loglevel', 'error'
        ], capture_output=True, check=True, timeout=10)

        if thumb_path.exists():
            return f"tweets/{tweet_id}/{thumb_name}"
    except Exception as e:
        logger.warning(f"Thumbnail generation failed for {video_path.name}: {e}")

    return ''


def import_markdown_bookmarks(output_dir: Path, profile: TwitterProfile) -> int:
    """Import birdmarks markdown files into Django database."""
    imported_count = 0
    md_files = list(output_dir.glob("*.md"))

    logger.info(f"Found {len(md_files)} markdown files to import")

    for md_file in md_files:
        try:
            content = md_file.read_text(encoding='utf-8')
            frontmatter, body = parse_frontmatter(content)

            tweet_id = frontmatter.get('id')
            if not tweet_id:
                continue

            # Skip if already exists
            if Tweet.objects.filter(tweet_id=tweet_id).exists():
                logger.debug(f"Skipping duplicate tweet {tweet_id}")
                continue

            # Parse date
            date_str = frontmatter.get('date', '')
            try:
                if date_str:
                    created_at = datetime.fromisoformat(str(date_str))
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=dt_timezone.utc)
                else:
                    created_at = timezone.now()
            except (ValueError, TypeError):
                created_at = timezone.now()

            # Extract text
            text_content = extract_tweet_text(body)

            # Create Tweet
            tweet = Tweet.objects.create(
                twitter_profile=profile,
                tweet_id=tweet_id,
                author_username=frontmatter.get('author', ''),
                author_display_name=frontmatter.get('author_name', ''),
                author_id='',
                text_content=text_content,
                html_content='',
                html_content_sanitized='',
                created_at=created_at,
                like_count=0,
                retweet_count=0,
                reply_count=frontmatter.get('reply_count', 0),
                is_bookmark=True,
                is_reply=False,
                processing_date=timezone.now().date()
            )

            # Import media from markdown
            media_count = import_tweet_media(tweet, body, output_dir)
            if media_count > 0:
                logger.info(f"  Imported {media_count} media file(s) for tweet {tweet_id}")

            imported_count += 1
            logger.info(f"Imported tweet {tweet_id} by @{tweet.author_username}")

        except Exception as e:
            logger.error(f"Failed to import {md_file.name}: {e}")
            continue

    return imported_count


def export_django_tweets_to_bookmarks_json():
    """Export all Django tweets to master/bookmarks.json format, merging with existing data."""
    bookmarks_file = MASTER_DIR / 'bookmarks.json'

    # Load existing bookmarks (preserves categories, media URLs, etc.)
    existing = {}
    if bookmarks_file.exists():
        try:
            with open(bookmarks_file) as f:
                for b in json.load(f):
                    existing[b['Tweet Id']] = b
        except Exception as e:
            logger.error(f"Failed to load existing bookmarks.json: {e}")

    # Export Django tweets and merge (new tweets override, existing keep extra fields)
    tweets = Tweet.objects.all().order_by('-created_at')
    new_count = 0
    for tweet in tweets:
        tid = tweet.tweet_id
        if tid in existing:
            # Update text but keep categories/media from existing
            existing[tid]['Full Text'] = tweet.text_content
            existing[tid]['Scraped At'] = tweet.scraped_at.isoformat() if tweet.scraped_at else ''
        else:
            # New tweet - create bookmark entry
            created_str = tweet.created_at.strftime('%a %b %d %H:%M:%S %z %Y') if tweet.created_at else ''
            existing[tid] = {
                'Tweet Id': tid,
                'Full Text': tweet.text_content,
                'Created At': created_str,
                'Scraped At': tweet.scraped_at.isoformat() if tweet.scraped_at else '',
                'Tweet URL': f'https://twitter.com/{tweet.author_username}/status/{tid}',
                'User Screen Name': tweet.author_username,
                'User Name': tweet.author_display_name or tweet.author_username,
                'User Avatar Url': tweet.author_profile_image_url or '',
                'User Description': '',
                'User Location': '',
                'User Followers Count': '',
                'User Is Blue Verified': '',
                'Retweet Count': str(tweet.retweet_count) if tweet.retweet_count else '',
                'Reply Count': str(tweet.reply_count) if tweet.reply_count else '',
                'Favorite Count': str(tweet.like_count) if tweet.like_count else '',
                'Media URLs': '',
                'Media Types': '',
            }
            new_count += 1

    # Sort by Created At (newest first) and save
    all_bookmarks = sorted(existing.values(),
                          key=lambda b: b.get('Scraped At', ''),
                          reverse=True)

    MASTER_DIR.mkdir(parents=True, exist_ok=True)
    with open(bookmarks_file, 'w') as f:
        json.dump(all_bookmarks, f, indent=2, ensure_ascii=False)

    logger.info(f"Exported {len(all_bookmarks)} bookmarks to {bookmarks_file} ({new_count} new)")
    return new_count


def regenerate_static_site():
    """Regenerate the static bookmarks HTML site after sync."""
    try:
        bookmarks_file = MASTER_DIR / 'bookmarks.json'
        if not bookmarks_file.exists():
            logger.warning("No bookmarks.json found, skipping static site regeneration")
            return False

        merger_script = TOOLS_DIR / 'bookmark_merger.py'
        if not merger_script.exists():
            logger.warning(f"bookmark_merger.py not found at {merger_script}")
            return False

        # Run generate first (creates timeline, stories, authors in master/html/)
        # then publish-server (creates server-optimized HTML from master/html/)
        logger.info("Regenerating static site: generate + publish-server...")
        gen_result = subprocess.run(
            [sys.executable, str(merger_script), 'generate'],
            capture_output=True, text=True, timeout=300,
            cwd=str(TOOLS_DIR.parent)
        )
        if gen_result.returncode != 0:
            logger.warning(f"generate step had issues: {gen_result.stderr[:300]}")

        result = subprocess.run(
            [sys.executable, str(merger_script), 'publish-server'],
            capture_output=True, text=True, timeout=300,
            cwd=str(TOOLS_DIR.parent)  # Run from project root
        )

        if result.returncode != 0:
            logger.error(f"publish-server failed: {result.stderr[:500]}")
            return False

        logger.info(f"Static site generated: {result.stdout[-200:]}")

        # Copy server/html/ to bookmarks-html/ (server serves from bookmarks-html/)
        if SERVER_HTML_DIR.exists() and BOOKMARKS_HTML_DIR.exists():
            import shutil
            # Sync HTML files (not media - that's separate)
            for item in SERVER_HTML_DIR.iterdir():
                dest = BOOKMARKS_HTML_DIR / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            logger.info(f"Copied static site to {BOOKMARKS_HTML_DIR}")

        return True
    except Exception as e:
        logger.error(f"Static site regeneration failed: {e}")
        return False


def execute_bookmark_sync(sync_job_id: int):
    """
    Execute bookmark sync via birdmarks_bridge.py.
    Called by Django-Q worker.
    """
    try:
        job = BookmarkSyncJob.objects.select_related('twitter_profile', 'twitter_profile__sync_schedule').get(id=sync_job_id)
        profile = job.twitter_profile
        schedule = profile.sync_schedule

        # Guard: Prevent premature execution (fix for runaway scheduling bug)
        now = timezone.now()
        if job.scheduled_at > now:
            time_until = (job.scheduled_at - now).total_seconds()
            logger.warning(
                f"Job #{job.id} executed too early! Scheduled for {job.scheduled_at}, "
                f"but it's only {now} ({time_until:.0f}s too early). "
                f"This indicates a Django-Q scheduling issue. Job will be skipped."
            )
            # Don't reschedule - the Django-Q schedule should handle it
            return

        # Call birdmarks binary directly (bypass bridge script to avoid subprocess nesting)
        birdmarks_bin = Path(__file__).parent.parent.parent / "birdmarks" / "birdmarks"
        # Use persistent dir so birdmarks state file and assets survive between runs
        output_dir = Path(__file__).parent.parent.parent / "birdmarks_cache"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get cookies from database
        credentials = profile.get_credentials()
        if not credentials or 'cookies' not in credentials:
            raise Exception("No cookies found in profile credentials")

        cookies = credentials['cookies']

        # Convert list format to dict format if needed
        if isinstance(cookies, list):
            cookie_dict = {c['name']: c['value'] for c in cookies if 'name' in c and 'value' in c}
        else:
            cookie_dict = cookies

        # Verify essential cookies exist
        if 'auth_token' not in cookie_dict or 'ct0' not in cookie_dict:
            raise Exception("Missing auth_token or ct0 in cookies")

        # Build command WITHOUT credentials in args
        cmd = [str(birdmarks_bin), str(output_dir)]

        if schedule.use_until_synced:
            cmd.append("--rebuild")
            # Clear stale cursor so rebuild always starts from page 1 (newest)
            state_file = output_dir / "exporter-state.json"
            if state_file.exists():
                state_file.unlink()
                logger.info("Cleared birdmarks state file for fresh rebuild")
        else:
            cmd.extend(["--max-pages", str(schedule.max_pages)])

        # Pass cookies as environment variables (birdmarks reads AUTH_TOKEN and CT0 from env)
        env = os.environ.copy()
        env['AUTH_TOKEN'] = cookie_dict['auth_token']
        env['CT0'] = cookie_dict['ct0']

        # Mark as running just before execution (fix race condition)
        job.status = 'running'
        job.started_at = timezone.now()
        job.save()

        logger.info(f"Starting bookmark sync for {profile.twitter_username} (job #{job.id})")
        logger.info(f"Command: {' '.join(cmd)}")
        logger.info(f"ENV: AUTH_TOKEN={len(env.get('AUTH_TOKEN', ''))} chars, CT0={len(env.get('CT0', ''))} chars")

        # Execute with timeout
        logger.info("Executing birdmarks binary...")
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=600  # 10-minute timeout
        )

        stdout = result.stdout
        stderr = result.stderr
        logger.info(f"Binary returned: exit_code={result.returncode}, stdout_len={len(stdout)}, stderr_len={len(stderr)}")

        # Store birdmarks output as job log (visible in admin)
        job.error_message = (stderr or stdout or '')[:4000]
        job.save()

        # --- Post-fetch pipeline: always runs all steps ---
        # Step 1: Import new tweets to DB (skips duplicates)
        md_files = list(output_dir.glob("*.md")) if output_dir.exists() else []
        logger.info(f"Found {len(md_files)} .md files in {output_dir}")

        bookmarks_count = 0
        try:
            bookmarks_count = import_markdown_bookmarks(output_dir, profile)
            logger.info(f"Imported {bookmarks_count} new bookmarks into database")
        except Exception as import_error:
            logger.error(f"Failed to import bookmarks: {import_error}")

        # Step 2: Sync ALL media from cache to bookmarks-media/ (not just new tweets)
        media_copied = 0
        try:
            media_copied = sync_all_media(output_dir)
        except Exception as media_error:
            logger.error(f"Media sync failed: {media_error}")

        # Step 3: Export all tweets to master/bookmarks.json
        try:
            new_exported = export_django_tweets_to_bookmarks_json()
            logger.info(f"Exported {new_exported} new tweets to master/bookmarks.json")
        except Exception as export_error:
            logger.error(f"Export to bookmarks.json failed: {export_error}")

        # Step 4: Categorize uncategorized tweets via Anthropic API
        categorized = 0
        try:
            categorized = categorize_uncategorized_tweets()
        except Exception as cat_error:
            logger.error(f"Categorization failed: {cat_error}")

        # Step 5: Regenerate static site HTML
        try:
            regenerate_static_site()
        except Exception as regen_error:
            logger.error(f"Static site regeneration failed: {regen_error}")

        # --- Determine success/failure ---
        # Success if: birdmarks connected (md files exist OR exit code 0)
        # This handles rate-limited partial fetches as success
        has_cache_data = len(md_files) > 0
        error_text = (stderr or '') + (stdout or '')

        if result.returncode == 0 or has_cache_data:
            job.status = 'success'
            job.bookmarks_fetched = bookmarks_count
            job.completed_at = timezone.now()

            schedule.consecutive_failures = 0
            schedule.backoff_multiplier = 1
            schedule.last_error_type = ''

            profile.last_sync_at = timezone.now()
            profile.sync_status = 'success'
            profile.sync_error_message = ''

            summary = (
                f"Sync OK: {bookmarks_count} new tweets, "
                f"{media_copied} media copied, {categorized} categorized"
            )
            logger.info(f"{summary} for {profile.twitter_username}")
            # Append summary to job log (birdmarks output already saved)
            job.error_message = (job.error_message or '') + f"\n\n--- RESULT ---\n{summary}"
        else:
            # True failure: birdmarks couldn't connect at all
            error_type = 'unknown'
            if 'auth_token' in error_text or 'ct0' in error_text or 'Cookies file not found' in error_text:
                error_type = 'cookie_expired'
            elif 'timeout' in error_text.lower():
                error_type = 'timeout'
            elif 'rate limit' in error_text.lower() or 'Rate Limited' in error_text:
                error_type = 'rate_limit'
            else:
                error_type = 'fetch_error'

            job.status = 'failed'
            job.error_message = (stderr or stdout or '')[:1000]
            job.error_type = error_type
            job.completed_at = timezone.now()

            schedule.consecutive_failures += 1
            schedule.last_error_type = error_type

            logger.error(f"Bookmark sync failed for {profile.twitter_username}: {error_type}")

            profile.sync_status = 'error'
            profile.sync_error_message = f"{error_type}: {(stderr or stdout or '')[:200]}"

        profile.save()
        schedule.save()
        job.save()

        # Handle failure: cookie_expired disables after 5 failures; transient errors use backoff
        if job.status == 'failed':
            if error_type == 'cookie_expired' and schedule.should_disable_due_to_failures():
                schedule.disable_due_to_failures()
                profile.sync_status = 'error'
                profile.sync_error_message = f'Sync disabled: cookies expired ({schedule.consecutive_failures} failures)'
                profile.save()
            elif error_type != 'cookie_expired':
                # Transient error: increase backoff, always reschedule
                schedule.backoff_multiplier = min(schedule.backoff_multiplier * 2, 12)
                schedule.save()
                logger.info(f"Transient failure for {profile.twitter_username}, backoff={schedule.backoff_multiplier}x")
                schedule_next_bookmark_sync(profile.id)
            else:
                # cookie_expired but under threshold: still reschedule (user may fix cookies)
                schedule_next_bookmark_sync(profile.id)
        elif schedule.enabled:
            # Success: schedule next sync
            schedule_next_bookmark_sync(profile.id)

    except subprocess.TimeoutExpired:
        # Timeout error
        job.status = 'failed'
        job.error_message = 'Sync timed out after 10 minutes'
        job.error_type = 'timeout'
        job.completed_at = timezone.now()
        job.save()

        logger.error(f"Bookmark sync timeout for job #{job.id}")

        # Transient error: increase backoff and reschedule
        try:
            profile_refresh = TwitterProfile.objects.select_related('sync_schedule').get(id=job.twitter_profile_id)
            schedule = profile_refresh.sync_schedule
            schedule.consecutive_failures += 1
            schedule.last_error_type = 'timeout'
            schedule.backoff_multiplier = min(schedule.backoff_multiplier * 2, 12)
            schedule.save()
            logger.info(f"Timeout for {profile_refresh.twitter_username}, backoff={schedule.backoff_multiplier}x")
            schedule_next_bookmark_sync(profile_refresh.id)
        except Exception as schedule_error:
            logger.error(f"Failed to schedule next sync after timeout for profile {job.twitter_profile_id}: {schedule_error}")

    except Exception as e:
        # Unexpected error - log full traceback
        logger.exception(f"Unexpected error in bookmark sync job {sync_job_id}: {e}")

        job.status = 'failed'
        job.error_message = str(e)[:1000]
        job.error_type = 'system_error'
        job.completed_at = timezone.now()
        job.save()

        # Transient error: increase backoff and reschedule
        try:
            profile_refresh = TwitterProfile.objects.select_related('sync_schedule').get(id=job.twitter_profile_id)
            schedule = profile_refresh.sync_schedule
            schedule.consecutive_failures += 1
            schedule.last_error_type = 'system_error'
            schedule.backoff_multiplier = min(schedule.backoff_multiplier * 2, 12)
            schedule.save()
            logger.info(f"System error for {profile_refresh.twitter_username}, backoff={schedule.backoff_multiplier}x")
            schedule_next_bookmark_sync(profile_refresh.id)
        except Exception as schedule_error:
            logger.error(f"Failed to schedule next sync after error for profile {job.twitter_profile_id}: {schedule_error}")


def schedule_next_bookmark_sync(twitter_profile_id: int):
    """
    Schedule the next bookmark sync for a profile.
    """
    try:
        profile = TwitterProfile.objects.select_related('sync_schedule').get(id=twitter_profile_id)
        schedule = profile.sync_schedule

        if not schedule.enabled:
            logger.info(f"Skipping schedule for {profile.twitter_username} - schedule disabled")
            return

        # Calculate next sync time
        next_sync = schedule.calculate_next_sync()

        # Validate next_sync is in the future
        now = timezone.now()
        if next_sync <= now:
            logger.warning(f"Calculated next_sync {next_sync} is not in future for {profile.twitter_username}, adjusting")
            next_sync = now + timedelta(minutes=schedule.interval_minutes)

        # Cancel any orphan pending jobs for this profile
        orphans = BookmarkSyncJob.objects.filter(
            twitter_profile=profile, status='pending'
        )
        orphan_count = orphans.count()
        if orphan_count:
            orphans.update(status='failed', error_type='cancelled',
                          error_message='Cancelled: superseded by newer scheduled job')
            logger.info(f"Cancelled {orphan_count} orphan pending job(s) for {profile.twitter_username}")

        # Create pending job
        job = BookmarkSyncJob.objects.create(
            twitter_profile=profile,
            scheduled_at=next_sync,
            status='pending'
        )

        # Delete any existing pending Django-Q schedules for this profile to avoid duplicates
        stale = DjangoQSchedule.objects.filter(
            func='twitter.tasks.execute_bookmark_sync',
            name__startswith=f"bookmark_sync_{profile.id}_"
        )
        stale_count = stale.count()
        if stale_count:
            logger.info(f"Cleaning up {stale_count} stale Django-Q schedule(s) for {profile.twitter_username}")
            stale.delete()

        # Update schedule
        schedule.next_sync_at = next_sync
        schedule.last_scheduled_at = timezone.now()
        schedule.save()

        # Queue task for future execution using schedule() with one-time execution
        from django_q.tasks import schedule
        schedule_name = f"bookmark_sync_{profile.id}_{job.id}"
        schedule_id = schedule(
            'twitter.tasks.execute_bookmark_sync',
            job.id,
            name=schedule_name,
            next_run=next_sync,
            schedule_type='O',  # Once
            repeats=1  # Run once and delete
        )

        logger.info(f"Scheduled bookmark sync for {profile.twitter_username} at {next_sync} (job #{job.id}, schedule={schedule_name})")

    except BookmarkSyncSchedule.DoesNotExist:
        # No schedule configured, skip
        logger.warning(f"No sync schedule found for profile {twitter_profile_id}")
    except Exception as e:
        # Log error but don't raise
        logger.exception(f"Error scheduling next sync for profile {twitter_profile_id}: {e}")
