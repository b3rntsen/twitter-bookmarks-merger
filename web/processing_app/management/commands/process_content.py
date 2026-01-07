"""
Management command to manually process a content job.
"""
from django.core.management.base import BaseCommand
from processing_app.models import ContentProcessingJob
from processing_app.tasks import process_content_job


class Command(BaseCommand):
    help = 'Manually process a specific content processing job'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'job_id',
            type=int,
            help='ID of ContentProcessingJob to process',
        )
    
    def handle(self, *args, **options):
        job_id = options['job_id']
        
        try:
            job = ContentProcessingJob.objects.get(id=job_id)
        except ContentProcessingJob.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"Job {job_id} not found")
            )
            return
        
        self.stdout.write(f"Processing job {job_id}...")
        self.stdout.write(f"  User: {job.user.username}")
        self.stdout.write(f"  Content Type: {job.content_type}")
        self.stdout.write(f"  Processing Date: {job.processing_date}")
        self.stdout.write(f"  Status: {job.status}")
        
        # Process job
        process_content_job(job_id)
        
        # Refresh job to get updated status
        job.refresh_from_db()
        
        self.stdout.write(
            self.style.SUCCESS(f"Job {job_id} processed. Status: {job.status}")
        )
        
        if job.status == 'completed':
            self.stdout.write(f"  Items processed: {job.items_processed}")
        elif job.status == 'failed':
            self.stdout.write(
                self.style.ERROR(f"  Error: {job.error_message}")
            )

