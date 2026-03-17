"""
Django management command to delete bookmarks within a specific date range.

This is used for cleanup when bookmarks were imported without media or with other issues.
After deletion, a rebuild sync can be queued to re-fetch the bookmarks properly.

Usage:
    python manage.py cleanup_date_range --start-date 2026-03-01 --end-date 2026-03-09 --dry-run
    python manage.py cleanup_date_range --start-date 2026-03-01 --end-date 2026-03-09 --confirm
"""
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from twitter.models import Tweet, TweetMedia


class Command(BaseCommand):
    help = 'Delete bookmarks within a specific date range for cleanup/rebuild'

    def add_arguments(self, parser):
        parser.add_argument(
            '--start-date',
            type=str,
            required=True,
            help='Start date (YYYY-MM-DD)',
        )
        parser.add_argument(
            '--end-date',
            type=str,
            required=True,
            help='End date (YYYY-MM-DD, inclusive)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview what would be deleted without actually deleting',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirm deletion (required for actual deletion)',
        )

    def handle(self, *args, **options):
        start_date_str = options['start_date']
        end_date_str = options['end_date']
        dry_run = options['dry_run']
        confirm = options['confirm']

        # Parse dates
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError as e:
            self.stdout.write(self.style.ERROR(f'Invalid date format: {e}'))
            self.stdout.write('Use YYYY-MM-DD format (e.g., 2026-03-01)')
            return

        # Add one day to end_date to make it inclusive
        end_datetime = timezone.make_aware(
            datetime.combine(end_date, datetime.max.time())
        )
        start_datetime = timezone.make_aware(
            datetime.combine(start_date, datetime.min.time())
        )

        if start_date > end_date:
            self.stdout.write(self.style.ERROR('Start date must be before end date'))
            return

        # Query bookmarks in date range
        tweets_to_delete = Tweet.objects.filter(
            created_at__gte=start_datetime,
            created_at__lte=end_datetime
        ).order_by('created_at')

        total_tweets = tweets_to_delete.count()

        if total_tweets == 0:
            self.stdout.write(self.style.WARNING(
                f'No bookmarks found between {start_date} and {end_date}'
            ))
            return

        # Count media files
        media_count = TweetMedia.objects.filter(tweet__in=tweets_to_delete).count()
        tweets_with_media = tweets_to_delete.filter(media__isnull=False).distinct().count()
        tweets_without_media = total_tweets - tweets_with_media

        # Show statistics
        self.stdout.write('=' * 60)
        self.stdout.write(f'Date range: {start_date} to {end_date}')
        self.stdout.write('=' * 60)
        self.stdout.write(f'Bookmarks to delete: {total_tweets}')
        self.stdout.write(f'  - With media: {tweets_with_media} ({media_count} media files)')
        self.stdout.write(f'  - Without media: {tweets_without_media} ({tweets_without_media/total_tweets*100:.1f}%)')
        self.stdout.write('')

        # Show sample tweets
        sample_tweets = tweets_to_delete[:5]
        self.stdout.write('Sample tweets (first 5):')
        for tweet in sample_tweets:
            media_info = f'{tweet.media.count()} media' if tweet.media.exists() else 'no media'
            self.stdout.write(
                f'  - {tweet.created_at.strftime("%Y-%m-%d")}: @{tweet.author_username} '
                f'({media_info})'
            )

        if total_tweets > 5:
            self.stdout.write(f'  ... and {total_tweets - 5} more')

        self.stdout.write('')

        # Dry run mode
        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY RUN MODE ==='))
            self.stdout.write('No bookmarks were deleted.')
            self.stdout.write('')
            self.stdout.write('To actually delete, run:')
            self.stdout.write(
                f'  python manage.py cleanup_date_range '
                f'--start-date {start_date_str} --end-date {end_date_str} --confirm'
            )
            return

        # Require confirmation for actual deletion
        if not confirm:
            self.stdout.write(self.style.ERROR('Missing --confirm flag'))
            self.stdout.write('To delete these bookmarks, add --confirm flag')
            self.stdout.write('To preview without deleting, use --dry-run')
            return

        # Final confirmation
        self.stdout.write(self.style.WARNING(
            f'\n⚠️  WARNING: About to DELETE {total_tweets} bookmarks!'
        ))
        self.stdout.write('This action CANNOT be undone.')
        self.stdout.write('')

        # Perform deletion
        try:
            with transaction.atomic():
                # Delete media first (cascade should handle this, but being explicit)
                deleted_media = TweetMedia.objects.filter(tweet__in=tweets_to_delete).delete()

                # Delete tweets
                deleted_tweets = tweets_to_delete.delete()

                self.stdout.write('')
                self.stdout.write(self.style.SUCCESS('✓ Deletion complete'))
                self.stdout.write(f'  - Deleted {deleted_tweets[0]} bookmarks')
                self.stdout.write(f'  - Deleted {deleted_media[0]} media files')
                self.stdout.write('')
                self.stdout.write('Next steps:')
                self.stdout.write('  1. Queue rebuild sync job to re-fetch these bookmarks')
                self.stdout.write('  2. Monitor sync progress in Django admin')
                self.stdout.write('  3. Verify media coverage after sync completes')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Deletion failed: {e}'))
            raise
