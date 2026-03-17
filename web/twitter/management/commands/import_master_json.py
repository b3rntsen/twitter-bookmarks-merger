"""
Django management command to import bookmarks from master/bookmarks.json.

Usage:
    python manage.py import_master_json --dry-run
    python manage.py import_master_json
    python manage.py import_master_json --force
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from twitter.models import Tweet, TweetMedia, TwitterProfile

logger = logging.getLogger(__name__)


def parse_twitter_date(date_str: str) -> datetime:
    """Parse Twitter date format to timezone-aware datetime.

    Format: "Sun Mar 01 00:00:00 +0000 2026"
    Returns: datetime object with UTC timezone
    """
    if not date_str:
        return timezone.now()

    try:
        # Twitter format: "Sun Mar 01 00:00:00 +0000 2026"
        dt = datetime.strptime(date_str, '%a %b %d %H:%M:%S %z %Y')
        return dt
    except Exception as e:
        logger.warning(f"Failed to parse Twitter date '{date_str}': {e}")
        return timezone.now()


def parse_iso_date(date_str: str) -> datetime:
    """Parse ISO format date to timezone-aware datetime.

    Format: "2026-03-02T16:56:56.253319"
    Returns: datetime object with UTC timezone
    """
    if not date_str:
        return timezone.now()

    try:
        import pytz
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        # Ensure timezone awareness
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        return dt
    except Exception as e:
        logger.warning(f"Failed to parse ISO date '{date_str}': {e}")
        return timezone.now()


def safe_int(value, default: int = 0) -> int:
    """Convert string to int, return default if empty or invalid."""
    if value is None or value == "":
        return default

    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def parse_media_fields(media_urls: str, media_types: str) -> list:
    """Parse comma-separated media URLs and types into list of dicts.

    Args:
        media_urls: "local:HCPvGyxbsAA5e_H.jpg, local:HCP5pOGbMAEtOAs.jpg"
        media_types: "photo, photo, video"

    Returns:
        [
            {"url": "local:HCPvGyxbsAA5e_H.jpg", "type": "image"},
            {"url": "local:HCP5pOGbMAEtOAs.jpg", "type": "image"}
        ]
    """
    if not media_urls or not media_types:
        return []

    urls = [u.strip() for u in media_urls.split(',') if u.strip()]
    types = [t.strip() for t in media_types.split(',') if t.strip()]

    media_list = []
    for url, media_type in zip(urls, types):
        # Map "photo" to "image" for consistency
        if media_type.lower() == 'photo':
            media_type = 'image'

        media_list.append({
            'url': url,
            'type': media_type.lower()
        })

    return media_list


def create_tweet_from_json(bookmark: dict, profile: TwitterProfile) -> Tweet:
    """Create Tweet object from JSON bookmark data (doesn't save).

    Args:
        bookmark: Dict from master/bookmarks.json
        profile: TwitterProfile to associate with

    Returns:
        Unsaved Tweet object
    """
    # Parse dates
    created_at = parse_twitter_date(bookmark.get('Created At', ''))
    scraped_at = parse_iso_date(bookmark.get('Scraped At', ''))

    # Parse engagement counts
    reply_count = safe_int(bookmark.get('Reply Count'))
    retweet_count = safe_int(bookmark.get('Retweet Count'))
    like_count = safe_int(bookmark.get('Favorite Count'))

    # Create Tweet object
    tweet = Tweet(
        twitter_profile=profile,
        tweet_id=bookmark['Tweet Id'],
        author_username=bookmark.get('User Screen Name', ''),
        author_display_name=bookmark.get('User Name', ''),
        author_id='',
        text_content=bookmark.get('Full Text', ''),
        html_content='',
        html_content_sanitized='',
        created_at=created_at,
        like_count=like_count,
        retweet_count=retweet_count,
        reply_count=reply_count,
        is_bookmark=True,
        is_reply=False,
        scraped_at=scraped_at,
        processing_date=scraped_at.date()
    )

    return tweet


def create_tweet_media(tweet: Tweet, media_list: list) -> int:
    """Create TweetMedia objects for a tweet.

    Args:
        tweet: Saved Tweet instance
        media_list: List of {"url": "...", "type": "..."} dicts

    Returns:
        Count of media objects created
    """
    if not media_list:
        return 0

    media_objects = []
    for media in media_list:
        media_obj = TweetMedia(
            tweet=tweet,
            media_type=media['type'],
            original_url=media['url'],
            file_path=media['url'],  # Use local: path as file_path
            file_size=0  # Unknown, set to 0
        )
        media_objects.append(media_obj)

    if media_objects:
        TweetMedia.objects.bulk_create(media_objects, ignore_conflicts=True)

    return len(media_objects)


class Command(BaseCommand):
    help = 'Import bookmarks from master/bookmarks.json into Django database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview import without writing to database',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Reimport existing tweets (update with JSON data)',
        )
        parser.add_argument(
            '--profile-id',
            type=int,
            default=3,
            help='TwitterProfile ID (default: 3)',
        )
        parser.add_argument(
            '--json-path',
            type=str,
            default=None,
            help='Override JSON file path (default: master/bookmarks.json)',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Batch insert size (default: 100)',
        )
        parser.add_argument(
            '--skip-media',
            action='store_true',
            help='Skip TweetMedia creation (default: False)',
        )

    def handle(self, *args, **options):
        # Parse options
        dry_run = options['dry_run']
        force = options['force']
        profile_id = options['profile_id']
        batch_size = options['batch_size']
        skip_media = options['skip_media']

        # Determine JSON path
        if options['json_path']:
            json_path = Path(options['json_path'])
        else:
            # Default: master/bookmarks.json relative to project root
            json_path = Path(__file__).parent.parent.parent.parent.parent / 'master' / 'bookmarks.json'

        # Validate inputs
        if not json_path.exists():
            raise CommandError(f"JSON file not found: {json_path}")

        # Get TwitterProfile
        try:
            profile = TwitterProfile.objects.get(id=profile_id)
            self.stdout.write(f"Using profile: @{profile.twitter_username} (ID={profile.id})")
        except TwitterProfile.DoesNotExist:
            raise CommandError(f"TwitterProfile with ID {profile_id} not found")

        # Load JSON data
        self.stdout.write("Loading JSON data...")
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                bookmarks = json.load(f)
        except Exception as e:
            raise CommandError(f"Failed to load JSON: {e}")

        self.stdout.write(self.style.SUCCESS(f"✓ Loaded {len(bookmarks)} bookmarks from JSON"))

        # Get existing tweet IDs
        self.stdout.write("Checking existing tweets...")
        existing_ids = set(Tweet.objects.values_list('tweet_id', flat=True))
        self.stdout.write(f"Found {len(existing_ids)} existing tweets in database")

        # Calculate what would be imported
        new_bookmarks = [b for b in bookmarks if b.get('Tweet Id') not in existing_ids]
        duplicate_count = len(bookmarks) - len(new_bookmarks)

        # Dry run preview
        if dry_run:
            self.stdout.write(self.style.WARNING("\n=== DRY RUN MODE ==="))
            self.stdout.write(f"Would import: {len(new_bookmarks)} new bookmarks")
            self.stdout.write(f"Would skip: {duplicate_count} duplicates")

            # Show sample of what would be imported
            samples = new_bookmarks[:3]
            if samples:
                self.stdout.write("\nSample tweets to import:")
                for b in samples:
                    text = b.get('Full Text', '')[:60]
                    self.stdout.write(f"  - {b['Tweet Id']}: @{b.get('User Screen Name')}: {text}...")
            return

        # Import in batches
        self.stdout.write("\nStarting import...")
        total_stats = {'imported': 0, 'skipped': 0, 'updated': 0, 'errors': []}

        for i in range(0, len(bookmarks), batch_size):
            batch = bookmarks[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(bookmarks) + batch_size - 1) // batch_size

            self.stdout.write(f"Processing batch {batch_num}/{total_batches}...")

            batch_stats = self._import_batch(
                batch, profile, existing_ids, force, skip_media
            )

            # Aggregate stats
            total_stats['imported'] += batch_stats['imported']
            total_stats['skipped'] += batch_stats['skipped']
            total_stats['updated'] += batch_stats['updated']
            total_stats['errors'].extend(batch_stats['errors'])

            # Progress indicator
            progress_pct = ((i + len(batch)) / len(bookmarks)) * 100
            self.stdout.write(
                f"  Progress: {progress_pct:.1f}% - "
                f"Imported: {batch_stats['imported']}, "
                f"Skipped: {batch_stats['skipped']}"
            )

        # Final report
        self.stdout.write("\n" + "="*60)
        self.stdout.write(self.style.SUCCESS("IMPORT COMPLETE"))
        self.stdout.write("="*60)
        self.stdout.write(f"Total processed: {len(bookmarks)}")
        self.stdout.write(self.style.SUCCESS(f"Imported: {total_stats['imported']}"))
        self.stdout.write(f"Skipped (duplicates): {total_stats['skipped']}")
        if force:
            self.stdout.write(f"Updated: {total_stats['updated']}")
        if total_stats['errors']:
            self.stdout.write(self.style.ERROR(f"Errors: {len(total_stats['errors'])}"))
            self.stdout.write("\nFirst 5 errors:")
            for error in total_stats['errors'][:5]:
                self.stdout.write(f"  - {error}")

        # Verification query
        final_count = Tweet.objects.count()
        expected_count = len(existing_ids) + total_stats['imported']
        self.stdout.write(f"\nTotal tweets in database: {final_count}")
        self.stdout.write(f"Expected: {expected_count}")

        if final_count == expected_count:
            self.stdout.write(self.style.SUCCESS("✓ Count verification passed"))
        else:
            self.stdout.write(self.style.WARNING(
                f"⚠ Count mismatch: expected {expected_count}, got {final_count}"
            ))

    def _import_batch(self, batch, profile, existing_ids, force, skip_media):
        """Import a batch of bookmarks with transaction safety."""
        stats = {'imported': 0, 'skipped': 0, 'updated': 0, 'errors': []}
        tweets_to_create = []

        try:
            with transaction.atomic():
                for bookmark in batch:
                    try:
                        tweet_id = bookmark.get('Tweet Id')
                        if not tweet_id:
                            continue

                        # Skip duplicates unless force mode
                        if tweet_id in existing_ids:
                            if not force:
                                stats['skipped'] += 1
                                continue
                            else:
                                # Update existing tweet
                                Tweet.objects.filter(tweet_id=tweet_id).update(
                                    text_content=bookmark.get('Full Text', ''),
                                    like_count=safe_int(bookmark.get('Favorite Count')),
                                    retweet_count=safe_int(bookmark.get('Retweet Count')),
                                    reply_count=safe_int(bookmark.get('Reply Count')),
                                )
                                stats['updated'] += 1
                                continue

                        # Create new tweet
                        tweet = create_tweet_from_json(bookmark, profile)
                        tweets_to_create.append(tweet)

                    except Exception as e:
                        error_msg = f"Tweet {bookmark.get('Tweet Id')}: {type(e).__name__}: {str(e)}"
                        logger.error(error_msg)
                        stats['errors'].append(error_msg)
                        continue

                # Bulk create tweets
                if tweets_to_create:
                    Tweet.objects.bulk_create(tweets_to_create, ignore_conflicts=True)
                    stats['imported'] = len(tweets_to_create)

                    # Note: Media creation skipped after bulk_create because
                    # ignore_conflicts=True prevents IDs from being set.
                    # Media can be added in a separate pass if needed.

        except Exception as e:
            error_msg = f"Batch error: {type(e).__name__}: {str(e)}"
            logger.error(error_msg)
            stats['errors'].append(error_msg)

        return stats
