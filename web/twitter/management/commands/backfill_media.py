"""
Django management command to backfill TweetMedia records from master/media/ directory.

Usage:
    python manage.py backfill_media --dry-run
    python manage.py backfill_media
    python manage.py backfill_media --force
"""
import shutil
import subprocess
import logging
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction
from twitter.models import Tweet, TweetMedia

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Backfill TweetMedia records from master/media/ directory'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview what would be done without making changes',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Recreate existing TweetMedia records',
        )
        parser.add_argument(
            '--source-dir',
            type=str,
            default='master/media',
            help='Source directory (default: master/media)',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Batch size for processing (default: 100)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        source_dir = Path(options['source_dir'])
        batch_size = options['batch_size']

        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY RUN MODE ==='))

        # Resolve source directory
        if not source_dir.is_absolute():
            # Relative to project root
            source_dir = Path(__file__).parent.parent.parent.parent.parent / source_dir

        if not source_dir.exists():
            self.stdout.write(self.style.ERROR(f'Source directory not found: {source_dir}'))
            return

        self.stdout.write(f'Scanning: {source_dir}')

        # Find all tweet directories
        tweet_dirs = [d for d in source_dir.iterdir() if d.is_dir() and d.name.isdigit()]
        self.stdout.write(f'Found {len(tweet_dirs)} tweet directories')

        # Get all tweet IDs from database
        tweet_ids_in_db = set(Tweet.objects.values_list('tweet_id', flat=True))
        self.stdout.write(f'Tweets in database: {len(tweet_ids_in_db)}')

        # Match directories to tweets
        matched_dirs = []
        orphaned_dirs = []

        for tweet_dir in tweet_dirs:
            tweet_id = tweet_dir.name
            if tweet_id in tweet_ids_in_db:
                matched_dirs.append(tweet_dir)
            else:
                orphaned_dirs.append(tweet_dir)

        self.stdout.write(f'Matched directories: {len(matched_dirs)}')
        if orphaned_dirs:
            self.stdout.write(self.style.WARNING(
                f'Orphaned directories (no matching tweet): {len(orphaned_dirs)}'
            ))

        # Count total media files to process
        total_media = 0
        for tweet_dir in matched_dirs:
            media_files = self._count_media_files(tweet_dir)
            total_media += media_files

        self.stdout.write(f'Total media files to process: {total_media}')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDRY RUN COMPLETE'))
            self.stdout.write(f'Would process {len(matched_dirs)} tweets with {total_media} media files')
            return

        # Process in batches
        self.stdout.write('\n=== Starting backfill ===')
        stats = {'processed': 0, 'media_created': 0, 'media_skipped': 0, 'errors': 0}

        for i in range(0, len(matched_dirs), batch_size):
            batch = matched_dirs[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(matched_dirs) + batch_size - 1) // batch_size

            self.stdout.write(f'\nProcessing batch {batch_num}/{total_batches}...')

            batch_stats = self._process_batch(batch, force)
            stats['processed'] += batch_stats['processed']
            stats['media_created'] += batch_stats['media_created']
            stats['media_skipped'] += batch_stats['media_skipped']
            stats['errors'] += batch_stats['errors']

            progress_pct = ((i + len(batch)) / len(matched_dirs)) * 100
            self.stdout.write(
                f'  Progress: {progress_pct:.1f}% - '
                f'Created: {batch_stats["media_created"]}, '
                f'Skipped: {batch_stats["media_skipped"]}, '
                f'Errors: {batch_stats["errors"]}'
            )

        # Final report
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write(self.style.SUCCESS('BACKFILL COMPLETE'))
        self.stdout.write('=' * 60)
        self.stdout.write(f'Tweets processed: {stats["processed"]}')
        self.stdout.write(self.style.SUCCESS(f'Media created: {stats["media_created"]}'))
        self.stdout.write(f'Media skipped (already exists): {stats["media_skipped"]}')
        if stats['errors'] > 0:
            self.stdout.write(self.style.ERROR(f'Errors: {stats["errors"]}'))

        # Verification
        total_media_records = TweetMedia.objects.count()
        tweets_with_media = Tweet.objects.filter(media__isnull=False).distinct().count()
        self.stdout.write(f'\nTotal TweetMedia records: {total_media_records}')
        self.stdout.write(f'Tweets with media: {tweets_with_media}')
        if tweets_with_media > 0:
            avg = total_media_records / tweets_with_media
            self.stdout.write(f'Average media per tweet: {avg:.1f}')

    def _count_media_files(self, tweet_dir: Path) -> int:
        """Count media files in a directory (excluding thumbnails)."""
        count = 0
        for pattern in ['*.jpg', '*.png', '*.mp4', '*.gif', '*.webm']:
            for f in tweet_dir.glob(pattern):
                if not f.name.startswith('thumb_'):
                    count += 1
        return count

    def _process_batch(self, batch, force):
        """Process a batch of tweet directories."""
        stats = {'processed': 0, 'media_created': 0, 'media_skipped': 0, 'errors': 0}

        try:
            with transaction.atomic():
                for tweet_dir in batch:
                    try:
                        tweet_id = tweet_dir.name
                        tweet = Tweet.objects.get(tweet_id=tweet_id)

                        media_stats = self._process_tweet_media(tweet_dir, tweet, force)
                        stats['media_created'] += media_stats['created']
                        stats['media_skipped'] += media_stats['skipped']
                        stats['processed'] += 1

                    except Tweet.DoesNotExist:
                        logger.error(f'Tweet {tweet_dir.name} not found in database')
                        stats['errors'] += 1
                        continue
                    except Exception as e:
                        logger.error(f'Error processing {tweet_dir.name}: {e}')
                        stats['errors'] += 1
                        continue

        except Exception as e:
            logger.error(f'Batch error: {e}')
            stats['errors'] += 1

        return stats

    def _process_tweet_media(self, tweet_dir: Path, tweet: Tweet, force):
        """Process all media files for one tweet."""
        stats = {'created': 0, 'skipped': 0}

        # Find media files (exclude thumbnails)
        media_files = []
        for pattern in ['*.jpg', '*.png', '*.mp4', '*.gif', '*.webm']:
            for f in tweet_dir.glob(pattern):
                if not f.name.startswith('thumb_'):
                    media_files.append(f)

        for media_file in media_files:
            try:
                # Determine media type
                ext = media_file.suffix.lower()
                if ext in ['.mp4', '.webm', '.mov', '.m4v']:
                    media_type = 'video'
                elif ext in ['.gif']:
                    media_type = 'gif'
                else:
                    media_type = 'image'

                # Create Django media directory
                dest_dir = Path(settings.MEDIA_ROOT) / 'tweets' / str(tweet.tweet_id)
                dest_dir.mkdir(parents=True, exist_ok=True)

                # Copy media file
                dest_file = dest_dir / media_file.name
                relative_path = f"tweets/{tweet.tweet_id}/{media_file.name}"

                # Check if already exists
                existing = TweetMedia.objects.filter(tweet=tweet, file_path=relative_path).exists()
                if existing and not force:
                    stats['skipped'] += 1
                    continue

                # Delete existing if force mode
                if existing and force:
                    TweetMedia.objects.filter(tweet=tweet, file_path=relative_path).delete()

                # Copy file
                shutil.copy2(media_file, dest_file)
                file_size = dest_file.stat().st_size

                # Handle video thumbnail
                thumbnail_rel = ''
                if media_type == 'video':
                    # Try to copy existing thumbnail
                    thumb_source = tweet_dir / f"thumb_{media_file.stem}.jpg"
                    if thumb_source.exists():
                        thumb_dest = dest_dir / thumb_source.name
                        shutil.copy2(thumb_source, thumb_dest)
                        thumbnail_rel = f"tweets/{tweet.tweet_id}/{thumb_source.name}"
                    else:
                        # Generate new thumbnail
                        thumbnail_rel = self._generate_video_thumbnail(
                            dest_file, dest_dir, tweet.tweet_id
                        )

                # Create TweetMedia record
                TweetMedia.objects.create(
                    tweet=tweet,
                    media_type=media_type,
                    file_path=relative_path,
                    original_url=f"master://media/{tweet.tweet_id}/{media_file.name}",
                    thumbnail_path=thumbnail_rel,
                    file_size=file_size
                )
                stats['created'] += 1

            except Exception as e:
                logger.error(f'Error processing media {media_file.name}: {e}')
                continue

        return stats

    def _generate_video_thumbnail(self, video_path: Path, output_dir: Path, tweet_id: str) -> str:
        """Generate thumbnail for video using ffmpeg."""
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
            logger.warning(f'Thumbnail generation failed for {video_path.name}: {e}')

        return ''
