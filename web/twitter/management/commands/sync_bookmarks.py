"""
Django management command to sync Twitter bookmarks.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from twitter.models import TwitterProfile
from twitter.services import TwitterScraper, TwikitScraper
from bookmarks_app.services import BookmarkService
import os


class Command(BaseCommand):
    help = 'Sync Twitter bookmarks for all connected accounts or a specific user'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            help='Sync bookmarks for a specific user (email)',
        )
        parser.add_argument(
            '--use-twikit',
            action='store_true',
            help='Use Twikit library instead of Selenium',
        )

    def handle(self, *args, **options):
        use_twikit = options.get('use_twikit', False)
        username = options.get('username')
        use_playwright = os.getenv('USE_PLAYWRIGHT', 'False').lower() == 'true'
        
        if username:
            users = User.objects.filter(email=username)
        else:
            users = User.objects.filter(twitter_profiles__isnull=False).distinct()
        
        if not users.exists():
            self.stdout.write(self.style.WARNING('No users with Twitter profiles found.'))
            return
        
        for user in users:
            self.stdout.write(f'Syncing bookmarks for {user.email}...')
            
            try:
                profile = TwitterProfile.objects.get(user=user)
                credentials = profile.get_credentials()
                
                if not credentials:
                    self.stdout.write(self.style.ERROR(f'No credentials found for {user.email}'))
                    continue
                
                # Initialize scraper
                if use_twikit:
                    scraper = TwikitScraper(
                        username=credentials.get('username'),
                        password=credentials.get('password'),
                        cookies=credentials.get('cookies')
                    )
                else:
                    scraper = TwitterScraper(
                        username=credentials.get('username'),
                        password=credentials.get('password'),
                        cookies=credentials.get('cookies'),
                        use_playwright=use_playwright
                    )
                
                # Get bookmarks
                bookmarks = scraper.get_bookmarks(max_bookmarks=100)
                self.stdout.write(f'Found {len(bookmarks)} bookmarks')
                
                # Store bookmarks
                bookmark_service = BookmarkService(profile)
                stored_count = bookmark_service.store_bookmarks(bookmarks)
                
                # Update profile
                profile.sync_status = 'success'
                profile.save()
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Successfully synced {stored_count} bookmarks for {user.email}'
                    )
                )
                
                scraper.close()
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Error syncing for {user.email}: {str(e)}')
                )
                profile.sync_status = 'error'
                profile.sync_error_message = str(e)
                profile.save()

