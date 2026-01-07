"""
Management command to schedule daily content processing jobs.
"""
from django.core.management.base import BaseCommand
from processing_app.schedulers import DailyScheduler


class Command(BaseCommand):
    help = 'Schedule daily content processing jobs for all users'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Date to schedule jobs for (YYYY-MM-DD), defaults to today',
        )
    
    def handle(self, *args, **options):
        scheduler = DailyScheduler()
        
        # Parse date if provided
        target_date = None
        if options.get('date'):
            from datetime import datetime
            try:
                target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(
                    self.style.ERROR(f"Invalid date format: {options['date']}. Use YYYY-MM-DD")
                )
                return
        
        # Schedule jobs
        jobs = scheduler.schedule_daily_jobs(target_date=target_date)
        
        self.stdout.write(
            self.style.SUCCESS(f"Successfully scheduled {len(jobs)} jobs")
        )
        
        # Show breakdown by content type
        from collections import Counter
        content_types = Counter(job.content_type for job in jobs)
        for content_type, count in content_types.items():
            self.stdout.write(f"  - {content_type}: {count} jobs")

