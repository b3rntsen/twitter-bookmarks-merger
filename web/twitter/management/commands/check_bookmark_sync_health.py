"""
Health check command for bookmark sync system.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from twitter.models import BookmarkSyncJob, BookmarkSyncSchedule
from django_q.models import Schedule as DjangoQSchedule
import sys


class Command(BaseCommand):
    help = 'Check health of bookmark sync system'

    def handle(self, *args, **options):
        issues = []
        warnings = []

        # Check 1: Stale pending jobs
        stale_pending = BookmarkSyncJob.objects.filter(
            status='pending',
            scheduled_at__lt=timezone.now() - timedelta(hours=2)
        ).count()

        if stale_pending > 0:
            issues.append(f'{stale_pending} pending jobs older than 2 hours')

        # Check 2: Stuck running jobs
        stuck_running = BookmarkSyncJob.objects.filter(
            status='running',
            started_at__lt=timezone.now() - timedelta(minutes=15)
        ).count()

        if stuck_running > 0:
            issues.append(f'{stuck_running} jobs stuck in running state >15 min')

        # Check 3: Schedules with next_sync in past
        past_schedules = BookmarkSyncSchedule.objects.filter(
            enabled=True,
            next_sync_at__lt=timezone.now() - timedelta(hours=1)
        ).count()

        if past_schedules > 0:
            issues.append(f'{past_schedules} enabled schedules with next_sync_at >1 hour in past')

        # Check 4: Django-Q schedules missing
        enabled_count = BookmarkSyncSchedule.objects.filter(enabled=True).count()
        djangoq_count = DjangoQSchedule.objects.filter(
            func='twitter.tasks.execute_bookmark_sync'
        ).count()

        if enabled_count > 0 and djangoq_count == 0:
            issues.append(f'{enabled_count} enabled schedules but 0 Django-Q schedules found')

        # Check 5: Excessive failures
        failing_schedules = BookmarkSyncSchedule.objects.filter(
            consecutive_failures__gte=3
        ).count()

        if failing_schedules > 0:
            warnings.append(f'{failing_schedules} schedules with 3+ consecutive failures')

        # Print results
        if issues:
            self.stdout.write(self.style.ERROR('HEALTH CHECK FAILED'))
            for issue in issues:
                self.stdout.write(self.style.ERROR(f'  ✗ {issue}'))
            sys.exit(1)
        elif warnings:
            self.stdout.write(self.style.WARNING('HEALTH CHECK PASSED WITH WARNINGS'))
            for warning in warnings:
                self.stdout.write(self.style.WARNING(f'  ⚠ {warning}'))
            sys.exit(0)
        else:
            self.stdout.write(self.style.SUCCESS('HEALTH CHECK PASSED'))
            sys.exit(0)
