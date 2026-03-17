"""
Continuously backfill missing bookmarks by running birdmarks in cycles.

This command runs birdmarks fetch → import cycles until it reaches a target date range.
It handles rate limits automatically by waiting between cycles.

Usage:
    python manage.py continuous_backfill --target-date 2026-03-01
    python manage.py continuous_backfill --target-date 2026-03-01 --max-cycles 10
"""
import subprocess
import time
from pathlib import Path
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from twitter.models import TwitterProfile, Tweet
from twitter.tasks import import_markdown_bookmarks


class Command(BaseCommand):
    help = 'Continuously backfill bookmarks until target date is reached'

    def add_arguments(self, parser):
        parser.add_argument(
            '--target-date',
            type=str,
            required=True,
            help='Target date to backfill to (YYYY-MM-DD)'
        )
        parser.add_argument(
            '--max-cycles',
            type=int,
            default=50,
            help='Maximum number of fetch cycles (default: 50)'
        )
        parser.add_argument(
            '--wait-minutes',
            type=int,
            default=20,
            help='Minutes to wait between cycles (default: 20)'
        )

    def handle(self, *args, **options):
        target_date_str = options['target_date']
        max_cycles = options['max_cycles']
        wait_minutes = options['wait_minutes']

        # Parse target date
        try:
            target_date = timezone.make_aware(
                datetime.strptime(target_date_str, '%Y-%m-%d')
            )
        except ValueError:
            self.stdout.write(self.style.ERROR(f'Invalid date format: {target_date_str}'))
            return

        self.stdout.write('=' * 70)
        self.stdout.write('CONTINUOUS BACKFILL PROCESS')
        self.stdout.write('=' * 70)
        self.stdout.write(f'Target date: {target_date.strftime("%Y-%m-%d")}')
        self.stdout.write(f'Max cycles: {max_cycles}')
        self.stdout.write(f'Wait between cycles: {wait_minutes} minutes')
        self.stdout.write('')

        # Get profile and credentials
        profile = TwitterProfile.objects.first()
        if not profile:
            self.stdout.write(self.style.ERROR('No Twitter profile found'))
            return

        creds = profile.get_credentials()
        if not creds or 'cookies' not in creds:
            self.stdout.write(self.style.ERROR('No credentials found'))
            return

        cookies = creds['cookies']
        if isinstance(cookies, list):
            cookie_dict = {c['name']: c['value'] for c in cookies if 'name' in c and 'value' in c}
        else:
            cookie_dict = cookies

        auth_token = cookie_dict.get('auth_token')
        ct0 = cookie_dict.get('ct0')

        if not auth_token or not ct0:
            self.stdout.write(self.style.ERROR('Missing auth_token or ct0 in credentials'))
            return

        # Temporary output directory
        output_dir = Path('/tmp/continuous_backfill')
        birdmarks_bin = Path('/app/birdmarks/birdmarks')

        cycle = 0
        total_imported = 0

        while cycle < max_cycles:
            cycle += 1
            self.stdout.write('')
            self.stdout.write('=' * 70)
            self.stdout.write(f'CYCLE {cycle}/{max_cycles}')
            self.stdout.write('=' * 70)

            # Check if we've filled the target date range
            # For March 1-9 backfill, check if we have good coverage in that range
            range_end = target_date + timezone.timedelta(days=9)
            target_range_tweets = Tweet.objects.filter(
                twitter_profile=profile,
                created_at__gte=target_date,
                created_at__lt=range_end
            )

            target_count = target_range_tweets.count()
            self.stdout.write(f'Tweets in target range ({target_date.strftime("%Y-%m-%d")} to {range_end.strftime("%Y-%m-%d")}): {target_count}')

            # If we have a good number of tweets in target range, consider it filled
            # Assume ~5-10 bookmarks per day, so March 1-9 should have at least 40 tweets
            if target_count >= 40:
                tweets_with_media = target_range_tweets.filter(media__isnull=False).distinct().count()
                coverage = (tweets_with_media / target_count * 100) if target_count > 0 else 0

                self.stdout.write(self.style.SUCCESS(
                    f'\n✅ TARGET FILLED! Found {target_count} tweets in March 1-9 range'
                ))
                self.stdout.write(f'   Media coverage: {coverage:.1f}%')
                self.stdout.write(f'   Total imported across all cycles: {total_imported} bookmarks')
                return

            # Clean output directory
            if output_dir.exists():
                import shutil
                shutil.rmtree(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            # Run birdmarks
            self.stdout.write(f'\n⏳ Running birdmarks fetch...')

            env = {
                'AUTH_TOKEN': auth_token,
                'CT0': ct0,
                'PATH': subprocess.os.environ.get('PATH', ''),
            }

            try:
                result = subprocess.run(
                    [str(birdmarks_bin), str(output_dir), '--rebuild'],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=600
                )

                # Show last 10 lines of output
                output_lines = result.stdout.split('\n')
                for line in output_lines[-10:]:
                    if line.strip():
                        self.stdout.write(f'  {line}')

            except subprocess.TimeoutExpired:
                self.stdout.write(self.style.WARNING('  Birdmarks timed out (10 min limit)'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Birdmarks failed: {e}'))

            # Count markdown files
            md_files = list(output_dir.glob('*.md'))
            self.stdout.write(f'\n📊 Fetched {len(md_files)} bookmarks')

            if len(md_files) == 0:
                self.stdout.write(self.style.WARNING('  No new bookmarks fetched - may have reached end or hit rate limit'))

                if cycle >= max_cycles:
                    self.stdout.write(self.style.WARNING(f'\n⚠️  Reached max cycles ({max_cycles}) without reaching target date'))
                    self.stdout.write(f'Total imported: {total_imported} bookmarks')
                    self.stdout.write('')
                    self.stdout.write('Options:')
                    self.stdout.write('  1. Run again with higher --max-cycles')
                    self.stdout.write('  2. Wait 15 minutes and run again (rate limit may have cleared)')
                    return

                self.stdout.write(f'\n⏳ Waiting {wait_minutes} minutes for rate limit to clear...')
                time.sleep(wait_minutes * 60)
                continue

            # Import into database
            self.stdout.write(f'\n📥 Importing into database...')
            try:
                imported = import_markdown_bookmarks(output_dir, profile)
                total_imported += imported
                self.stdout.write(self.style.SUCCESS(f'  ✅ Imported {imported} bookmarks'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  ❌ Import failed: {e}'))

            # Check progress toward target
            march_tweets = Tweet.objects.filter(
                twitter_profile=profile,
                created_at__gte=target_date,
                created_at__lt=target_date + timezone.timedelta(days=9)
            )
            self.stdout.write(f'\n📊 March 1-9 progress:')
            self.stdout.write(f'  Tweets in database: {march_tweets.count()}')

            # Wait before next cycle (unless this is the last one)
            if cycle < max_cycles:
                self.stdout.write(f'\n⏳ Waiting {wait_minutes} minutes before next cycle...')
                time.sleep(wait_minutes * 60)

        # Reached max cycles
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(f'⚠️  Reached max cycles ({max_cycles}) without fully reaching target date'))
        self.stdout.write(f'Total imported: {total_imported} bookmarks')
        self.stdout.write('')
        self.stdout.write('Run again to continue backfilling.')
