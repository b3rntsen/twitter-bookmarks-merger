from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule as DjangoQSchedule
from twitter.models import TwitterProfile, BookmarkSyncSchedule, BookmarkSyncJob
from twitter.tasks import schedule_next_bookmark_sync


WATCHDOG_NAME = 'bookmark_sync_watchdog'
WATCHDOG_FUNC = 'twitter.tasks.recover_stuck_bookmark_syncs'
WATCHDOG_INTERVAL_MINUTES = 30


def ensure_recovery_watchdog():
    desired = {
        'func': WATCHDOG_FUNC,
        'schedule_type': DjangoQSchedule.MINUTES,
        'minutes': WATCHDOG_INTERVAL_MINUTES,
        'repeats': -1,
    }
    sched, created = DjangoQSchedule.objects.get_or_create(
        name=WATCHDOG_NAME,
        defaults={**desired, 'next_run': timezone.now() + timedelta(minutes=1)},
    )
    if not created:
        changed = False
        for field, value in desired.items():
            if getattr(sched, field) != value:
                setattr(sched, field, value)
                changed = True
        if changed:
            sched.save()
    return sched, created


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

        if not profiles.exists():
            self.stdout.write(
                self.style.WARNING(
                    'No Twitter profiles found. Connect a Twitter account first.'
                )
            )
            return

        # Ensure the periodic recovery watchdog is registered. Independent of
        # any sync run, so a crashed sync can't strand the scheduler.
        try:
            _, created = ensure_recovery_watchdog()
            self.stdout.write(self.style.SUCCESS(
                f"{'Created' if created else 'Verified'} recovery watchdog "
                f"(runs every {WATCHDOG_INTERVAL_MINUTES} min)"
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to register recovery watchdog: {e}'))

        # Recover any jobs stuck in 'running' state (likely from worker crash/restart)
        stale_cutoff = timezone.now() - timedelta(minutes=30)
        stuck_running = BookmarkSyncJob.objects.filter(
            status='running',
            started_at__lt=stale_cutoff
        )
        stuck_count = stuck_running.count()
        if stuck_count:
            stuck_running.update(
                status='failed',
                error_type='stale_job',
                error_message='Automatically recovered on startup: stuck in running >30 min',
                completed_at=timezone.now()
            )
            self.stdout.write(
                self.style.WARNING(
                    f'Recovered {stuck_count} stuck running job(s) from previous container lifecycle'
                )
            )

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
                schedule_next_bookmark_sync(profile.id)
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Scheduled first sync for {profile.twitter_username}'
                    )
                )
            elif not schedule.enabled:
                # Re-enable schedules disabled by transient errors (not cookie expiration)
                if schedule.last_error_type != 'cookie_expired':
                    schedule.enabled = True
                    schedule.backoff_multiplier = 4  # Start with longer interval after recovery
                    schedule.consecutive_failures = 0
                    schedule.save()
                    schedule_next_bookmark_sync(profile.id)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Re-enabled sync schedule for {profile.twitter_username} '
                            f'(was disabled by: {schedule.last_error_type or "unknown"})'
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Sync schedule for {profile.twitter_username} disabled due to '
                            f'expired cookies — re-enable manually after updating cookies'
                        )
                    )
            elif schedule.enabled and (not schedule.next_sync_at or schedule.next_sync_at < timezone.now()):
                # Enabled but no next sync or stale next_sync_at (e.g. after container restart)
                schedule_next_bookmark_sync(profile.id)
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Rescheduled sync for {profile.twitter_username}'
                    )
                )
            else:
                self.stdout.write(
                    f'Sync schedule already active for {profile.twitter_username} '
                    f'(next: {schedule.next_sync_at})'
                )
