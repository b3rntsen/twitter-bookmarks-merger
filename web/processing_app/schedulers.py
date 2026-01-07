"""
Scheduler for daily content processing jobs.
"""
from typing import List, Optional
from datetime import date, datetime, time as dt_time
from django.utils import timezone
from django.contrib.auth.models import User
from django_q.tasks import async_task, schedule
from processing_app.models import ContentProcessingJob, ProcessingSchedule
from twitter.models import TwitterProfile


class DailyScheduler:
    """Schedules daily content processing jobs."""
    
    CONTENT_TYPES = ['bookmarks', 'curated_feed', 'lists']
    
    def schedule_daily_jobs(self, target_date: Optional[date] = None) -> List[ContentProcessingJob]:
        """
        Schedule processing jobs for all users for a given date.
        
        Args:
            target_date: Date to schedule jobs for (defaults to today)
            
        Returns:
            List of created ContentProcessingJob instances
        """
        if target_date is None:
            target_date = date.today()
        
        created_jobs = []
        
        # Get all users with enabled ProcessingSchedule
        schedules = ProcessingSchedule.objects.filter(enabled=True).select_related('user')
        
        for schedule_obj in schedules:
            user = schedule_obj.user
            
            # Check if user has TwitterProfile
            try:
                twitter_profile = TwitterProfile.objects.get(user=user)
            except TwitterProfile.DoesNotExist:
                continue
            
            # Schedule jobs for this user
            user_jobs = self.schedule_user_jobs(
                user=user,
                target_date=target_date,
                immediate=False
            )
            created_jobs.extend(user_jobs)
        
        return created_jobs
    
    def schedule_user_jobs(
        self,
        user: User,
        target_date: Optional[date] = None,
        immediate: bool = False
    ) -> List[ContentProcessingJob]:
        """
        Schedule processing jobs for a specific user.
        
        Args:
            user: User instance
            target_date: Date to schedule jobs for (defaults to today)
            immediate: If True, queue jobs immediately (for new user connections)
            
        Returns:
            List of created ContentProcessingJob instances
        """
        if target_date is None:
            target_date = date.today()
        
        # Get or create ProcessingSchedule
        try:
            processing_schedule = ProcessingSchedule.objects.get(user=user)
        except ProcessingSchedule.DoesNotExist:
            # Create default schedule
            processing_schedule = ProcessingSchedule.objects.create(
                user=user,
                enabled=True,
                processing_time=dt_time(2, 0),  # 2:00 AM UTC default
                timezone='UTC'
            )
        
        # Check if schedule is enabled
        if not processing_schedule.enabled:
            return []
        
        # Check if user has TwitterProfile
        try:
            twitter_profile = TwitterProfile.objects.get(user=user)
        except TwitterProfile.DoesNotExist:
            return []
        
        created_jobs = []
        
        # Schedule jobs for each enabled content type
        content_type_map = {
            'bookmarks': processing_schedule.process_bookmarks,
            'curated_feed': processing_schedule.process_curated_feed,
            'lists': processing_schedule.process_lists,
        }
        
        for content_type, is_enabled in content_type_map.items():
            if not is_enabled:
                continue
            
            # Check if job should be scheduled
            if not self.should_schedule_job(user, content_type, target_date, immediate):
                continue
            
            # Check if a failed job exists - if so, reset it instead of creating new
            existing_job = ContentProcessingJob.objects.filter(
                user=user,
                twitter_profile=twitter_profile,
                content_type=content_type,
                processing_date=target_date
            ).first()
            
            if existing_job and existing_job.status == 'failed':
                # Reset failed job for retry
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
                # Create new job
                job = ContentProcessingJob.objects.create(
                    user=user,
                    twitter_profile=twitter_profile,
                    content_type=content_type,
                    processing_date=target_date,
                    status='pending',
                    scheduled_at=timezone.now(),
                    retry_count=0,
                    max_retries=5
                )
            
            # Queue job
            if immediate:
                # Queue immediately
                async_task('processing_app.tasks.process_content_job', job.id)
            else:
                # Schedule for user's configured processing time
                schedule_time = self._get_schedule_time(processing_schedule, target_date)
                schedule(
                    'processing_app.tasks.process_content_job',
                    job.id,
                    next_run=schedule_time
                )
            
            created_jobs.append(job)
        
        return created_jobs
    
    def should_schedule_job(
        self,
        user: User,
        content_type: str,
        target_date: date,
        immediate: bool = False
    ) -> bool:
        """
        Check if a job should be scheduled for a user/content_type/date.
        
        Args:
            user: User instance
            content_type: 'bookmarks', 'curated_feed', or 'lists'
            target_date: Date to check
            immediate: If True, allow scheduling even if job exists (for retries)
            
        Returns:
            bool: True if job should be scheduled
        """
        # Validate content type
        if content_type not in self.CONTENT_TYPES:
            return False
        
        # Check user has ProcessingSchedule
        try:
            processing_schedule = ProcessingSchedule.objects.get(user=user)
        except ProcessingSchedule.DoesNotExist:
            return False
        
        # Check schedule is enabled
        if not processing_schedule.enabled:
            return False
        
        # Check content type is enabled
        content_type_map = {
            'bookmarks': processing_schedule.process_bookmarks,
            'curated_feed': processing_schedule.process_curated_feed,
            'lists': processing_schedule.process_lists,
        }
        if not content_type_map.get(content_type, False):
            return False
        
        # Check user has TwitterProfile
        if not TwitterProfile.objects.filter(user=user).exists():
            return False
        
        # Check job doesn't already exist (unless immediate or all existing jobs are failed)
        if not immediate:
            existing_jobs = ContentProcessingJob.objects.filter(
                user=user,
                content_type=content_type,
                processing_date=target_date
            )
            if existing_jobs.exists():
                # Allow rescheduling if all existing jobs are failed
                non_failed_jobs = existing_jobs.exclude(status='failed')
                if non_failed_jobs.exists():
                    return False  # Has active or completed jobs, don't reschedule
        
        # Check target_date is not in future (unless immediate)
        if not immediate and target_date > date.today():
            return False
        
        return True
    
    def _get_schedule_time(self, processing_schedule: ProcessingSchedule, target_date: date) -> datetime:
        """
        Get the scheduled time for a job based on user's processing schedule.
        
        Args:
            processing_schedule: ProcessingSchedule instance
            target_date: Date to schedule for
            
        Returns:
            datetime for when job should run
        """
        # Combine target_date with processing_time
        schedule_datetime = datetime.combine(target_date, processing_schedule.processing_time)
        
        # Make timezone-aware (assuming UTC for now)
        schedule_datetime = timezone.make_aware(schedule_datetime)
        
        # If scheduled time is in the past, schedule for tomorrow
        if schedule_datetime < timezone.now():
            schedule_datetime = schedule_datetime + timezone.timedelta(days=1)
        
        return schedule_datetime

