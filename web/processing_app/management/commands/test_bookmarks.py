"""
Management command to test bookmark processing through the queue.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date
from processing_app.models import ContentProcessingJob
from processing_app.schedulers import DailyScheduler
from twitter.models import TwitterProfile


class Command(BaseCommand):
    help = 'Test bookmark processing by creating a job and queuing it through Django-Q'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            help='Username to process bookmarks for (defaults to first user with Twitter profile)',
        )

    def handle(self, *args, **options):
        username = options.get('username')

        # Find user
        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"User '{username}' not found"))
                return
        else:
            # Get first user with Twitter profile
            user = User.objects.filter(twitter_profiles__isnull=False).first()
            if not user:
                self.stdout.write(self.style.ERROR("No users with Twitter profiles found"))
                return
        
        # Get Twitter profile
        twitter_profile = TwitterProfile.objects.filter(user=user).first()
        if not twitter_profile:
            self.stdout.write(self.style.ERROR(f"User '{user.username}' has no Twitter profile"))
            return

        self.stdout.write(self.style.SUCCESS(f"Testing bookmark processing for user: {user.username}"))
        self.stdout.write(f"Twitter profile: @{twitter_profile.twitter_username}")
        self.stdout.write("")

        # Create a test job using the scheduler
        today = date.today()
        
        # Check if job already exists and reset it if needed
        existing_job = ContentProcessingJob.objects.filter(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=today
        ).first()
        
        if existing_job:
            self.stdout.write(self.style.WARNING(f"Found existing bookmark job {existing_job.id}, resetting it..."))
            existing_job.status = 'pending'
            existing_job.retry_count = 0
            existing_job.scheduled_at = timezone.now()
            existing_job.started_at = None
            existing_job.completed_at = None
            existing_job.next_retry_at = None
            existing_job.error_message = ''
            existing_job.error_traceback = ''
            existing_job.items_processed = 0
            existing_job.save()
            job = existing_job
        else:
            scheduler = DailyScheduler()
            self.stdout.write(f"Creating and queuing bookmark job for {today}...")
            jobs = scheduler.schedule_user_jobs(
                user=user,
                target_date=today,
                immediate=True
            )
            
            # Filter for bookmark job
            bookmark_jobs = [j for j in jobs if j.content_type == 'bookmarks']
            if not bookmark_jobs:
                self.stdout.write(self.style.ERROR("Failed to create bookmark job"))
                return
            job = bookmark_jobs[0]
        
        # Queue the job immediately if it's not already queued
        from django_q.tasks import async_task
        if job.status == 'pending':
            async_task('processing_app.tasks.process_content_job', job.id, hook='processing_app.tasks.job_completion_hook')
            self.stdout.write(self.style.SUCCESS(f"✓ Bookmark job {job.id} queued"))
        else:
            self.stdout.write(self.style.SUCCESS(f"✓ Bookmark job {job.id} is {job.status}"))
        
        self.stdout.write(f"  Status: {job.status}")
        self.stdout.write(f"  Processing date: {job.processing_date}")
        self.stdout.write("")
        self.stdout.write("Monitor progress with:")
        self.stdout.write(f"  tail -f qcluster.log | grep -E '\\[BOOKMARKS\\]|\\[TASK\\]'")
        self.stdout.write("")
        self.stdout.write("Or check job status in Django admin or the processing status page.")

