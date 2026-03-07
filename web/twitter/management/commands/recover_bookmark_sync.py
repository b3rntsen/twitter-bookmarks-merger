"""
Django management command to recover from stale bookmark sync state.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from twitter.models import TwitterProfile, BookmarkSyncJob, BookmarkSyncSchedule
from twitter.tasks import schedule_next_bookmark_sync
from django_q.models import Schedule as DjangoQSchedule
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Recover from stale bookmark sync state - clean up stuck jobs and reschedule'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )
        parser.add_argument(
            '--stuck-threshold',
            type=int,
            default=30,
            help='Minutes threshold for stuck "running" jobs (default: 30)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        stuck_threshold = options['stuck_threshold']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))

        self.stdout.write(self.style.SUCCESS('=== Bookmark Sync Recovery ===\n'))

        # Step 1: Clean up stale pending jobs
        stale_pending = BookmarkSyncJob.objects.filter(
            status='pending',
            scheduled_at__lt=timezone.now() - timedelta(days=1)
        )

        self.stdout.write(f'Found {stale_pending.count()} stale pending jobs (scheduled >1 day ago)')

        if not dry_run:
            for job in stale_pending:
                self.stdout.write(f'  - Canceling job #{job.id} (scheduled {job.scheduled_at})')
                job.status = 'failed'
                job.error_message = 'Job canceled by recovery script - was stuck in pending'
                job.error_type = 'stale_job'
                job.completed_at = timezone.now()
                job.save()

        # Step 2: Clean up stuck running jobs
        stuck_running = BookmarkSyncJob.objects.filter(
            status='running',
            started_at__lt=timezone.now() - timedelta(minutes=stuck_threshold)
        )

        self.stdout.write(f'\nFound {stuck_running.count()} stuck running jobs (running >{stuck_threshold} min)')

        if not dry_run:
            for job in stuck_running:
                self.stdout.write(f'  - Marking job #{job.id} as failed (started {job.started_at})')
                job.status = 'failed'
                job.error_message = f'Job marked as failed by recovery script - was stuck in running for >{stuck_threshold} minutes'
                job.error_type = 'stale_job'
                job.completed_at = timezone.now()
                job.save()

        # Step 3: Clean up orphaned Django-Q schedules
        orphaned_schedules = DjangoQSchedule.objects.filter(
            func='twitter.tasks.execute_bookmark_sync'
        )

        self.stdout.write(f'\nFound {orphaned_schedules.count()} Django-Q schedules for bookmark sync')

        if not dry_run:
            for schedule in orphaned_schedules:
                self.stdout.write(f'  - Deleting Django-Q schedule {schedule.id} ({schedule.name})')
                schedule.delete()

        # Step 4: Fix schedules with next_sync_at in the past
        schedules_in_past = BookmarkSyncSchedule.objects.filter(
            enabled=True,
            next_sync_at__lt=timezone.now()
        )

        self.stdout.write(f'\nFound {schedules_in_past.count()} schedules with next_sync_at in the past')

        # Step 5: Reschedule all enabled schedules
        enabled_schedules = BookmarkSyncSchedule.objects.filter(enabled=True).select_related('twitter_profile')

        self.stdout.write(f'\nRescheduling {enabled_schedules.count()} enabled schedules...')

        if not dry_run:
            for schedule in enabled_schedules:
                try:
                    self.stdout.write(f'  - Rescheduling {schedule.twitter_profile.twitter_username}...')
                    schedule_next_bookmark_sync(schedule.twitter_profile.id)
                    schedule.refresh_from_db()
                    self.stdout.write(self.style.SUCCESS(f'    ✓ Scheduled for {schedule.next_sync_at}'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'    ✗ Error: {e}'))

        # Step 6: Report summary
        self.stdout.write(self.style.SUCCESS('\n=== Recovery Summary ==='))
        self.stdout.write(f'Stale pending jobs: {stale_pending.count()}')
        self.stdout.write(f'Stuck running jobs: {stuck_running.count()}')
        self.stdout.write(f'Orphaned Django-Q schedules: {orphaned_schedules.count()}')
        self.stdout.write(f'Schedules rescheduled: {enabled_schedules.count()}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN COMPLETE - Run without --dry-run to apply changes'))
        else:
            self.stdout.write(self.style.SUCCESS('\nRECOVERY COMPLETE'))
