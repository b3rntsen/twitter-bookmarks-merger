from django.core.management.base import BaseCommand
from twitter.models import TwitterProfile, BookmarkSyncSchedule
from twitter.tasks import schedule_next_bookmark_sync


class Command(BaseCommand):
    help = 'Initialize bookmark sync schedules for all Twitter profiles'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=60,
            help='Sync interval in minutes (default: 60)'
        )
        parser.add_argument(
            '--max-pages',
            type=int,
            default=2,
            help='Max pages to fetch per sync (default: 2)'
        )

    def handle(self, *args, **options):
        profiles = TwitterProfile.objects.all()

        for profile in profiles:
            # Create or update sync schedule
            schedule, created = BookmarkSyncSchedule.objects.get_or_create(
                twitter_profile=profile,
                defaults={
                    'enabled': True,
                    'interval_minutes': options['interval'],
                    'max_pages': options['max_pages'],
                }
            )

            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Created sync schedule for {profile.twitter_username}'
                    )
                )

                # Schedule first sync
                schedule_next_bookmark_sync(profile.id)
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Scheduled first sync for {profile.twitter_username}'
                    )
                )
            else:
                self.stdout.write(
                    f'Sync schedule already exists for {profile.twitter_username}'
                )

        if not profiles.exists():
            self.stdout.write(
                self.style.WARNING(
                    'No Twitter profiles found. Connect a Twitter account first.'
                )
            )
